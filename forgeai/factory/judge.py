"""Stage 5 - Judge. Deterministic checks decide; the LLM only breaks ties it is allowed to break.

Why not "just ask an LLM"? Three known biases, each with a concrete defence here:

* position bias   -> the LLM is asked twice with the required-facts list in opposite order. It can
                     only override the deterministic verdict if BOTH votes agree; a split vote is
                     recorded as ``judge_unstable`` and the deterministic result stands.
* self-preference -> the judge model is configured separately (a different family when possible);
                     the report warns when judge model == agent model.
* verbosity bias  -> the LLM never sees a free-form "is this good?" question. It answers yes/no per
                     required fact, the answer is truncated, and length is never part of the score.

Deterministic layer: refusal detection (flag + phrase regex), key-fact matching, citation validity,
and a groundedness check (answer tokens and every number must appear in the retrieved context).
The LLM is only called when a deterministic check is *ambiguous* (some but not all facts found).
"""

from __future__ import annotations

import re

from forgeai.llm.client import LLMClient, is_outage
from forgeai.llm.structured import generate_structured
from forgeai.prompts import render
from forgeai.schemas import AgentResponse, CaseResult, EvalCase, JudgeVote
from forgeai.textutil import fact_in, support_ratio

SUPPORT_MIN = 0.55
_CLARIFY = re.compile(
    r"(which (one|of|\w+)|do you mean|are you (asking|referring)|could you (clarify|specify|tell)|please (clarify|specify))[^?]*\?",
    re.I,
)
MAX_ANSWER_CHARS = 1200


def _vote(client: LLMClient, model: str, case: EvalCase, resp: AgentResponse, facts: list[str]) -> JudgeVote | None:
    prompt = render(
        "judge_facts",
        question=case.question,
        context=resp.context_text[:3500],
        answer=resp.answer[:MAX_ANSWER_CHARS],
        facts="\n".join(f"{i}. {f}" for i, f in enumerate(facts, 1)),
    )

    def check(v: JudgeVote) -> None:
        if len(v.facts_present) != len(facts):
            raise ValueError(f"facts_present must have {len(facts)} entries")

    try:
        return generate_structured(
            client,
            JudgeVote,
            [{"role": "user", "content": prompt}],
            model=model,
            stage="judge",
            max_tokens=200,
            retries=1,
            validator=check,
        ).value
    except Exception as exc:
        if is_outage(exc):
            raise
        return None


def judge_case(client: LLMClient, judge_model: str, case: EvalCase, resp: AgentResponse, use_llm: bool = True) -> CaseResult:
    base = dict(
        case_id=case.id, type=case.type, split=case.split, refused=resp.refused, answer=resp.answer, question=case.question
    )

    if case.expected_refusal:
        if resp.refused:
            return CaseResult(**base, passed=True)
        return CaseResult(
            **base,
            passed=False,
            grounded=False,
            failure="hallucination",
            judge_note="answered a question the documents cannot support",
        )

    if case.type == "ambiguous" and not resp.refused and _CLARIFY.search(resp.answer):
        return CaseResult(**base, passed=True, judge_note="asked a clarifying question")

    facts = case.key_facts
    ctx = resp.context_text
    retrieval_hit = all(fact_in(f, ctx) for f in facts)
    if resp.refused:
        return CaseResult(
            **base,
            passed=False,
            fact_coverage=0.0,
            retrieval_hit=retrieval_hit,
            failure="retrieval_miss" if not retrieval_hit else "wrong_refusal",
            judge_note="refused although facts " + ("were not retrieved" if not retrieval_hit else "were in the context"),
        )

    present = [fact_in(f, resp.answer) for f in facts]
    cov = sum(present) / len(facts) if facts else 1.0
    ratio, bad_nums = support_ratio(resp.answer, ctx, case.question)
    det_grounded = ratio >= SUPPORT_MIN and not bad_nums
    cites_ok = bool(resp.citations) and all(c in resp.retrieved or c.startswith("tool:") for c in resp.citations)
    if any(t.get("ok") for t in resp.tool_calls):
        cites_ok = True

    note, unstable, overrode = [], False, False
    grounded = det_grounded
    if use_llm and facts and not all(present) and case.type != "tool":
        v1 = _vote(client, judge_model, case, resp, facts)
        v2_facts = list(reversed(facts))
        v2 = _vote(client, judge_model, case, resp, v2_facts)
        if v1 and v2:
            v2_present = list(reversed(v2.facts_present))
            if v1.facts_present == v2_present:
                if all(v1.facts_present) and not all(present):
                    present, overrode = [True] * len(facts), True
                    note.append("LLM judge (2 agreeing votes) accepted paraphrased facts")
                if not v1.grounded and not v2.grounded and det_grounded:
                    grounded = False
                    note.append("LLM judge (2 agreeing votes) flagged unsupported claims")
            else:
                unstable = True
                note.append("judge votes disagreed under fact reordering; deterministic verdict kept")
        else:
            note.append("LLM judge unavailable; deterministic verdict kept")
    cov = sum(present) / len(facts) if facts else 1.0

    if not grounded:
        note.append(f"answer support {ratio:.2f}" + (f", numbers not in context: {sorted(bad_nums)}" if bad_nums else ""))
    facts_ok = cov >= 1.0
    passed = facts_ok and grounded and cites_ok
    failure = ""
    if not passed:
        if case.type == "tool":
            failure = "prompt_defect"
            used = [t["tool"] for t in resp.tool_calls] or ["none"]
            note.append(f"wrong or unsupported value; tools used: {used}; expected {case.reference_answer}")
        elif not facts_ok and not retrieval_hit:
            failure = "retrieval_miss"
        elif not grounded:
            failure = "hallucination"
        else:
            failure = "prompt_defect"
            note.append("facts missing from answer despite being retrieved" if not facts_ok else "missing or invalid citations")
    return CaseResult(
        **base,
        passed=passed,
        fact_coverage=round(cov, 2),
        grounded=grounded,
        citation_ok=cites_ok,
        retrieval_hit=retrieval_hit,
        failure=failure,
        judge_note="; ".join(note),
        judge_unstable=unstable,
        llm_overrode=overrode,
    )
