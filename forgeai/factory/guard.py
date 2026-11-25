"""Stage 2 - Groundability guard.

For every topic the client wants answered, ask the corpus itself. Two independent signals:

* lexical coverage: share of the topic's content words that occur in the top retrieved passages (deterministic)
* an LLM yes/partial/no verdict on those passages (small models over-say "yes", so it can only
  *lower* the deterministic status, never raise an "unsupported" topic back to supported)

Unsupported topics are removed from must_answer and recorded as ungrounded, which later
(1) becomes a prompt rule telling the agent to decline them and (2) feeds near-miss eval cases.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from forgeai.llm.client import LLMClient
from forgeai.llm.structured import generate_structured
from forgeai.prompts import render
from forgeai.retrieval.index import HybridIndex, SearchParams
from forgeai.schemas import Requirements, TopicCheck
from forgeai.textutil import content_tokens


class _Verdict(BaseModel):
    verdict: str = "partial"
    note: str = ""


def _stem(w: str) -> str:
    for suf in ("ion", "ing", "ies", "es", "s", "ed", "e"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def lexical_coverage(topic: str, passages: list[str]) -> float:
    want = {_stem(w) for w in content_tokens(topic)}
    if not want:
        return 1.0
    have = {_stem(w) for p in passages for w in content_tokens(p)}
    return len(want & have) / len(want)


# Tools that bring in information the documents cannot contain (live data). A topic they serve is not
# "ungrounded". Table and arithmetic tools are not listed: they only work on what the documents hold.
LIVE_DATA_TOOLS = {
    "weather": {"weather", "forecast", "temperature", "rainfall"},
    "current_date": {"today", "current date", "days remaining", "days left"},
}
_LIVE = re.compile(r"real.?time|live|current|today|now|forecast|latest", re.I)


def live_tool_for(topic: str) -> str:
    """Name of the live-data tool that serves this topic, or ''. Needs a live-data cue AND the tool's subject."""
    low = topic.lower()
    if not _LIVE.search(low):
        return ""
    return next((name for name, words in LIVE_DATA_TOOLS.items() if any(w in low for w in words)), "")


def check_topic(
    client: LLMClient, index: HybridIndex, topic: str, model: str | None = None, extra_evidence: str = ""
) -> TopicCheck:
    hits = index.search(topic, SearchParams(top_k=3, mode="hybrid"))
    # Evidence = best passages (with section headings) + what the available tools can do + table column names.
    texts = [h.chunk.text for h in hits] + ([extra_evidence] if extra_evidence else [])
    cov = lexical_coverage(topic, texts)
    passages = "\n---\n".join(f"[{h.chunk.chunk_id}] {h.chunk.body[:700]}" for h in hits) or "(nothing found)"
    verdict, note = "partial", ""
    if hits:
        res = generate_structured(
            client,
            _Verdict,
            [{"role": "user", "content": render("guard_topic", topic=topic, passages=passages)}],
            model=model,
            stage="guard",
            max_tokens=200,
            fallback=_Verdict(verdict="partial", note="llm unavailable"),
        )
        verdict, note = res.value.verdict.lower().strip(), res.value.note
    else:
        verdict = "no"

    # Two signals must AGREE before a topic is declared unsupported. A lexical miss alone is common for
    # tables (column names/values rarely echo the topic phrasing), so an LLM "yes" downgrades it to partial.
    if verdict == "no":
        status = "partial" if cov >= 0.67 else "unsupported"
    elif cov < 0.34:
        status = "partial" if verdict == "yes" else "unsupported"
        if verdict == "yes":
            note = (note + " ").lstrip() + "[low lexical overlap but LLM says supported: check manually]"
    elif cov >= 0.67 and verdict == "yes":
        status = "supported"
    else:
        status = "partial"
    tool = live_tool_for(topic)
    if tool and status == "unsupported":
        status, note = "partial", f"not in the documents; live data comes from the {tool} tool"
    return TopicCheck(
        topic=topic,
        status=status,
        lexical_coverage=round(cov, 2),
        best_chunks=[h.chunk.chunk_id for h in hits],
        llm_verdict=verdict,
        note=note,
    )


def run_guard(
    client: LLMClient, index: HybridIndex, req: Requirements, model: str | None = None, extra_evidence: str = ""
) -> Requirements:
    checks = [check_topic(client, index, t, model, extra_evidence) for t in req.must_answer_topics]
    unsupported = [c.topic for c in checks if c.status == "unsupported"]
    req.groundability = checks
    req.ungrounded_topics = unsupported
    kept = [t for t in req.must_answer_topics if t not in unsupported]
    req.must_answer_topics = kept or req.must_answer_topics  # never leave the agent with zero duties
    for c in checks:
        if c.status in ("unsupported", "partial"):
            req.assumptions.append(f"GROUNDABILITY {c.status.upper()}: '{c.topic}' (coverage {c.lexical_coverage}) - {c.note}")
    return req
