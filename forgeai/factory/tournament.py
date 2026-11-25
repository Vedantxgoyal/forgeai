"""Prompt tournament (optional): candidate role prompts compete on development cases.

Candidates differ in *answering strategy*, not in facts: the grounding, citation, refusal and tool rules are
identical, so a win can be attributed to the strategy. Only DEV cases are used - the hold-out stays unseen.
A candidate that introduces content absent from the documents is replaced by a vetted template.
"""

from __future__ import annotations

import copy

from pydantic import BaseModel

from forgeai.agent.runtime import Agent
from forgeai.config import Settings
from forgeai.factory.generator import _corpus_text, _invented_content
from forgeai.factory.optimizer import run_exam, score
from forgeai.ingest.loaders import LoadResult
from forgeai.llm.client import LLMClient
from forgeai.llm.structured import generate_structured
from forgeai.prompts import render
from forgeai.retrieval.index import HybridIndex
from forgeai.schemas import AgentDef, EvalCase, Requirements

STRATEGIES = {
    "quote-first": "Before answering, locate the exact sentence in the context that answers the question and build the answer from it.",
    "checklist": "Before answering, check every number, condition and exception that applies and include each one.",
}
MAX_CASES = 10


class _Prompt(BaseModel):
    role_prompt: str


def _pick(cases: list[EvalCase], limit: int) -> list[EvalCase]:
    """Dev cases only, taken round-robin across types."""
    by_type: dict[str, list[EvalCase]] = {}
    for c in sorted((c for c in cases if c.split == "dev"), key=lambda c: c.id):
        by_type.setdefault(c.type, []).append(c)
    out: list[EvalCase] = []
    while len(out) < limit and any(by_type.values()):
        for t in sorted(by_type):
            if by_type[t] and len(out) < limit:
                out.append(by_type[t].pop(0))
    return out


def run_tournament(
    base: AgentDef,
    load: LoadResult,
    req: Requirements,
    cases: list[EvalCase],
    client: LLMClient,
    settings: Settings,
    index: HybridIndex,
    workers: int = 4,
) -> tuple[AgentDef, list[dict]]:
    sample = _pick(cases, MAX_CASES)
    corpus = _corpus_text(load) + " " + req.brief.lower()
    candidates: list[tuple[str, AgentDef]] = [("as-generated", base)]
    for name, strategy in STRATEGIES.items():
        template = f"{base.role_prompt} {strategy}"
        draft = generate_structured(
            client,
            _Prompt,
            [{"role": "user", "content": render("tournament", role_prompt=base.role_prompt, strategy=strategy)}],
            model=settings.gen_model,
            stage="tournament",
            max_tokens=500,
            fallback=_Prompt(role_prompt=template),
        ).value.role_prompt.strip()
        if not draft or _invented_content(draft, corpus, req.ungrounded_topics):
            draft = template
        cand = copy.deepcopy(base)
        cand.role_prompt = draft
        candidates.append((name, cand))

    table: list[dict] = []
    for name, cand in candidates:
        results = run_exam(Agent(cand, load, client, settings, index=index), sample, client, settings.judge_model, workers)
        table.append(
            {
                "candidate": name,
                "passed": sum(r.passed for r in results),
                "total": len(results),
                "score": score(results),
                "words": len(cand.role_prompt.split()),
                "role_prompt": cand.role_prompt,
            }
        )
    # highest score wins; on a tie the earlier candidate (the unmodified one first) is kept: change needs evidence
    best = max(range(len(table)), key=lambda i: (table[i]["score"], -i))
    for i, row in enumerate(table):
        row["winner"] = i == best
    return candidates[best][1], table
