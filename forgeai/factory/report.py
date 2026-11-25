"""Stage 7 - Honest reporting. Written for a sceptical reader: it states what is NOT proven."""

from __future__ import annotations

import math

from forgeai.factory.optimizer import IterationLog
from forgeai.schemas import AgentDef, EvalCase, Requirements


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - m) / d), min(1.0, (c + m) / d)


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def render_report(
    title: str,
    req: Requirements,
    d0: AgentDef,
    d_final: AgentDef,
    cases: list[EvalCase],
    gen_stats: dict,
    logs: list[IterationLog],
    usage: dict,
    models: dict,
    manifest_notes: list[str],
    contest: list[dict] | None = None,
) -> str:
    final = logs[-1] if logs[-1].accepted else next(x for x in reversed(logs) if x.accepted)
    k, n = final.n_pass, final.n_total
    lo, hi = wilson(k, n)
    L: list[str] = [f"# ForgeAI quality report: {title}", ""]
    L += [
        "## Verdict",
        "",
        f"**Final agent (v{d_final.version}) passes {k}/{n} generated test cases ({_pct(k / n)}).** "
        f"With only {n} cases the 95% confidence interval is roughly **{_pct(lo)} - {_pct(hi)}**, so treat it as an estimate, not a guarantee.",
        f"Dev split {_pct(final.dev_score)} (used by the optimizer) vs hold-out {_pct(final.holdout_score)} (never inspected by it). "
        + (
            "Hold-out is close to dev: no obvious over-fitting."
            if abs(final.dev_score - final.holdout_score) <= 0.15
            else "A large dev/hold-out gap suggests the fixes may be tuned to the dev cases."
        ),
        "",
    ]

    L += [
        "## Scorecard per iteration",
        "",
        "| Iter | Agent | Overall | Dev | Hold-out | Failures by class | Outcome |",
        "|---|---|---|---|---|---|---|",
    ]
    for lg in logs:
        fc = ", ".join(f"{k_}:{v}" for k_, v in lg.failures_by_class.items()) or "none"
        L.append(
            f"| {lg.iteration} | v{lg.agent_version} | {lg.n_pass}/{lg.n_total} ({_pct(lg.overall_score)}) | {_pct(lg.dev_score)} | {_pct(lg.holdout_score)} | {fc} | {lg.note} |"
        )
    L += ["", "By case type (final): " + ", ".join(f"{t} {v}" for t, v in final.by_type.items()), ""]

    if contest:
        L += [
            "## Prompt tournament (development cases only)",
            "",
            "| Candidate | Passed | Prompt words | Result |",
            "|---|---|---|---|",
        ]
        L += [
            f"| {c['candidate']} | {c['passed']}/{c['total']} | {c['words']} | {'**winner**' if c['winner'] else ''} |"
            for c in contest
        ]
        L += ["", "Ties keep the unmodified prompt. With this few cases a one-case lead is weak evidence.", ""]

    L += ["## Change log (what the optimizer changed and why)", ""]
    any_change = False
    for lg in logs[1:]:
        for c in lg.changes:
            any_change = True
            sc = f"{_pct(lg.score_before)} -> {_pct(lg.overall_score)}" if lg.score_before is not None else ""
            L.append(
                f"- **Iter {lg.iteration} / {c.category} / {c.kind}** ({'kept' if lg.accepted else 'ROLLED BACK'}; overall {sc}): {c.detail}  \n"
                f"  targeted cases: {', '.join(c.addresses)}"
            )
    if not any_change:
        L.append("- No changes were needed or possible.")
    L.append("")

    L += ["## What still fails, and why", ""]
    fails = [r for r in final.results if not r.passed]
    if not fails:
        L.append(
            "Nothing failed on this exam. That does not mean the agent is perfect: the exam was generated from the same documents "
            "by a small model, so it can miss question styles real users will try."
        )
    for r in fails:
        L.append(
            f'- `{r.case_id}` ({r.type}, {r.split}) **{r.failure or "unclassified"}**: "{r.question}"  \n  agent said: "{r.answer[:160]}"  \n  judge: {r.judge_note or "-"}'
        )
    L.append("")

    L += ["## Requirements and groundability", "", f"Brief: {req.brief}", ""]
    for c in req.groundability:
        L.append(
            f"- **{c.status.upper()}** `{c.topic}` (lexical coverage {c.lexical_coverage}, LLM verdict {c.llm_verdict}) {c.note}"
        )
    if req.ungrounded_topics:
        L += [
            "",
            "Topics requested but NOT supported by the documents (agent instructed to decline): "
            + "; ".join(req.ungrounded_topics),
        ]
    L.append("")

    L += [
        "## Tools",
        "",
        "Chosen: "
        + (
            ", ".join(f'`{t.name}` (because: "{t.justification}")' for t in d_final.tools)
            or "none (no tool needed for this brief)"
        ),
    ]
    for x in d_final.dropped_tools:
        L.append(f"- dropped `{x['tool']}`: {x['reason']}")
    L.append("")

    L += [
        "## How trustworthy is this score?",
        "",
        f"- Exam: {gen_stats.get('kept')} cases kept of {gen_stats.get('proposed')} proposed; {gen_stats.get('dropped_unverified')} discarded because their key facts were not found verbatim in the source; "
        f"{gen_stats.get('dropped_answerable_refusal')} 'refusal' questions discarded because the documents could actually answer them. Types: {gen_stats.get('by_type')}.",
        f"- Judge: deterministic checks decide; LLM judge ({models['judge']}) only arbitrates when some key facts are missing, and counts only if two votes with reversed fact order agree.",
        f"  Overrides by LLM judge: {sum(r.llm_overrode for r in final.results)}; unstable judgements: {sum(r.judge_unstable for r in final.results)}.",
    ]
    over = sum(not r.contract_ok for r in final.results)
    L.append(
        f"- Output contract: {over} answer(s) exceeded the word limit of {d_final.output_contract.get('max_words', 'n/a')} (reported, not scored)."
    )
    if models["judge"] == models["agent"]:
        L.append(
            "- **Warning:** judge model and agent model are the same model, so self-preference bias is possible. Deterministic checks limit but do not remove it."
        )
    L += [
        "- The exam is generated from the same documents the agent retrieves from; it measures faithfulness to those documents, not real-world user satisfaction.",
        f"- Configured models: agent `{models['agent']}`, generator `{models['gen']}`, judge `{models['judge']}`.",
    ]
    L += [f"- {x}" for x in manifest_notes]
    tot = usage.get("_total", {})
    L += [
        "",
        "## Cost",
        "",
        f"{tot.get('calls')} LLM calls ({tot.get('cache_hits')} cache hits), {tot.get('total_tokens')} tokens, {tot.get('seconds')}s of model time.",
        "",
    ]
    L += ["## Final agent rules", ""] + [
        f"{i}. {r.text}" + (f"  _(added iter {r.added_in_iteration}: {r.category})_" if r.added_in_iteration else "")
        for i, r in enumerate(d_final.rules, 1)
    ]
    r = d_final.retrieval
    L += [
        "",
        f"Retrieval: chunk {r.chunk_size}/{r.chunk_overlap} words, top_k {r.top_k}, mode {r.mode}, rerank {r.rerank}, query_rewrite {r.query_rewrite}",
        "",
    ]
    return "\n".join(L)
