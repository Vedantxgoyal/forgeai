"""Stage 3 - Agent generator.

The system prompt is *composed*, not free-written: an LLM drafts the role paragraph and a few
domain rules, while grounding / citation / refusal rules come from a vetted skeleton and
requirement fields are inserted deterministically. Composition matters because the optimizer
later edits ONE rule at a time (a targeted fix) instead of regenerating the whole prompt.

Tool selection is gated: a tool survives only if it is (a) available for this corpus and
(b) justified by a quote that really occurs in the brief/requirements. Dropped tools are
recorded with the reason, so "why no weather tool?" has an answer in the artifact.
"""

from __future__ import annotations

import json

from rapidfuzz import fuzz

from forgeai.config import Settings
from forgeai.ingest.loaders import LoadResult
from forgeai.ingest.profiler import CorpusProfile
from forgeai.llm.client import LLMClient
from forgeai.llm.structured import generate_structured
from forgeai.prompts import render
from forgeai.schemas import AgentDef, RetrievalConfig, RoleDraft, Requirements, Rule, ToolChoice, ToolPicks
from forgeai.ingest.chunker import suggest_params
from forgeai.tools import REGISTRY, registry_cards
from forgeai.tools.base import ToolContext


def select_tools(client: LLMClient, req: Requirements, load: LoadResult, profile: CorpusProfile,
                 model: str | None = None) -> tuple[list[ToolChoice], list[dict]]:
    ctx = ToolContext(tables=load.tables)
    req_text = json.dumps(req.model_dump(exclude={"groundability", "qa"}), ensure_ascii=False)
    corpus_text = f"BRIEF: {req.brief}\nPURPOSE: {req.purpose}\nSCOPE: {req.scope}\nTOPICS: {', '.join(req.must_answer_topics)}"
    facts = f"{len(profile.docs)} documents; tables: {list(load.tables) or 'none'}"
    res = generate_structured(client, ToolPicks, [{"role": "user", "content": render(
        "agent_tools", requirements=req_text[:3500], facts=facts, cards=registry_cards(ctx))}],
        model=model, stage="generate", fallback=ToolPicks(), max_tokens=500)
    keep: list[ToolChoice] = []
    dropped: list[dict] = []
    seen: set[str] = set()
    for pick in res.value.tools:
        name = pick.name.strip()
        if name in seen:
            continue
        seen.add(name)
        tool = REGISTRY.get(name)
        if tool is None:
            dropped.append({"tool": name, "reason": "not in registry"})
            continue
        ok, why = tool.available(ctx)
        if not ok:
            dropped.append({"tool": name, "reason": f"unavailable: {why}"})
            continue
        quote = pick.justification.strip()
        score = fuzz.partial_ratio(quote.lower(), (corpus_text + " " + req_text).lower()) if len(quote) >= 12 else 0
        if score < 85:
            dropped.append({"tool": name, "reason": f"justification quote not found in brief/requirements (match {score:.0f}): {quote[:80]!r}"})
            continue
        keep.append(ToolChoice(name=name, justification=quote))
    # Deterministic safety net: tables exist but the model forgot the lookup tool.
    if load.tables and "csv_lookup" not in {t.name for t in keep}:
        keep.append(ToolChoice(name="csv_lookup", justification=f"corpus contains structured table(s): {', '.join(load.tables)}"))
    return keep, dropped


def _corpus_text(load: LoadResult) -> str:
    parts = [d.text for d in load.documents if d.table is None]
    parts += [t.astype(str).to_string(index=False) for t in load.tables.values()]
    return " ".join(parts).lower()


def _invented_content(rule: str, corpus: str, ungrounded: list[str]) -> str:
    """A generated domain rule may not introduce facts: numbers, currencies or uncovered topics."""
    import re

    for tok in re.findall(r"\d[\d.,]*\d|\d|[A-Z]{3,}", rule):
        if tok.lower() not in corpus:
            return f"introduces '{tok}', which appears in neither documents nor brief"
    low = rule.lower()
    for t in ungrounded:
        if t.lower() in low:
            return f"mentions uncovered topic '{t}'"
    return ""


GROUNDING_RULES = [
    ("g1", "Answer ONLY from the CONTEXT passages (and tool results). Never use outside knowledge, guesses or common sense to fill gaps.", "grounding"),
    ("g2", "Cite the chunk ids you used in \"citations\", e.g. [\"doc#3\"]. Cite only passages that actually contain the answer.", "citation"),
    ("g3", "If the CONTEXT does not contain the answer, set refused=true and use the refusal sentence. A partial answer must say what is missing.", "refusal"),
    ("g4", "Copy numbers, durations, names, codes and conditions exactly as written in the CONTEXT; never round or convert unless asked.", "faithfulness"),
]


def build_agent(client: LLMClient, req: Requirements, load: LoadResult, profile: CorpusProfile,
                settings: Settings, model: str | None = None) -> AgentDef:
    req_text = json.dumps(req.model_dump(exclude={"groundability", "qa", "assumptions"}), ensure_ascii=False)
    fb = RoleDraft(role_prompt=f"You are {req.agent_name.replace('_', ' ')}. {req.purpose} Your audience: {req.audience}. Tone: {req.tone}.", rules=[])
    draft = generate_structured(client, RoleDraft, [{"role": "user", "content": render("agent_role", requirements=req_text[:3500], ungrounded="; ".join(req.ungrounded_topics) or "none")}],
                                model=model, stage="generate", fallback=fb, max_tokens=700).value
    rules = [Rule(id=i, text=t, category=c) for i, t, c in GROUNDING_RULES]
    corpus_text = _corpus_text(load) + " " + req.brief.lower()
    dropped_rules: list[dict] = []
    for text in draft.rules[:5]:
        # Evidence-gated prompt: a model-written domain rule is NOT trusted into the prompt (small models invent
        # plausible policy). It is held back and logged; the optimizer may add rules only to fix a failing test.
        why = _invented_content(text, corpus_text, req.ungrounded_topics) or "held back: rules enter the prompt only when a failing test justifies them"
        dropped_rules.append({"rule": text.strip(), "reason": why})
    if req.must_refuse_topics:
        rules.append(Rule(id="s1", category="scope", text="Politely decline these topics, even if the CONTEXT mentions them: " + "; ".join(req.must_refuse_topics) + "."))
    if req.ungrounded_topics:
        rules.append(Rule(id="s2", category="scope", text="The documents do NOT cover: " + "; ".join(req.ungrounded_topics) + ". Say so instead of answering from general knowledge."))
    covered = "; ".join(t for t in req.must_answer_topics if t not in req.ungrounded_topics)
    rules.append(Rule(id="s3", category="scope", text=f"You only help with: {covered}. Questions unrelated to these topics are out of scope: refuse them in one sentence."))

    tools, dropped = select_tools(client, req, load, profile, model)
    names = {t.name for t in tools}
    if "csv_lookup" in names:
        rules.append(Rule(id="t1", category="tools", text="For the price, stock or any attribute of a specific record, call csv_lookup first and use the exact value it returns."))
    if "calculator" in names:
        rules.append(Rule(id="t2", category="tools", text="Never do arithmetic yourself: call the calculator for every total, difference or percentage, then report its result."))
    cp = suggest_params(load.documents)
    cfg = RetrievalConfig(chunk_size=cp.chunk_size, chunk_overlap=cp.chunk_overlap, top_k=5, mode="hybrid", rerank=False)
    return AgentDef(name=req.agent_name, model=settings.effective_agent_model, role_prompt=draft.role_prompt.strip(),
                    rules=rules, retrieval=cfg, tools=tools, dropped_tools=dropped, dropped_rules=dropped_rules)
