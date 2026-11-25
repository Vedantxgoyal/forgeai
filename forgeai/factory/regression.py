"""Regression mode: the documents changed - what broke?

The OLD exam is run against an agent REGENERATED from the new documents. A raw pass/fail diff would be
misleading, because an old expected answer may simply no longer be true. So each old case is first checked
against the new documents, deterministically:

* stale     - a fact (or table cell) the case depends on is gone or changed. A failure here is expected:
              the *test* is outdated, and the report says what changed.
* regression - the supporting facts are still there, the old agent passed, the new one does not. A real break.
* recheck   - a "must refuse" case the new documents may now be able to answer.

Rules and retrieval settings learned by the optimizer are carried into the regenerated agent, so a break
cannot be blamed on having thrown away earlier fixes.
"""

from __future__ import annotations

import difflib
import json
from collections.abc import Callable
from pathlib import Path

from forgeai.agent.runtime import Agent, build_index, load_agent_def, save_agent_def
from forgeai.config import Settings, get_settings
from forgeai.factory import generator, guard
from forgeai.factory.evalgen import _answerability
from forgeai.factory.optimizer import run_exam, score
from forgeai.ingest.loaders import LoadResult, load_folder
from forgeai.ingest.profiler import profile_corpus
from forgeai.llm.client import LLMClient
from forgeai.schemas import EvalCase, Requirements
from forgeai.textutil import fact_in


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def document_changes(old: LoadResult, new: LoadResult, limit: int = 12) -> list[dict]:
    a, b = {d.doc_id: d for d in old.documents}, {d.doc_id: d for d in new.documents}
    out = [{"doc": k, "change": "removed"} for k in sorted(a.keys() - b.keys())]
    out += [{"doc": k, "change": "added"} for k in sorted(b.keys() - a.keys())]
    for k in sorted(a.keys() & b.keys()):
        if a[k].content_hash == b[k].content_hash:
            continue
        lines = [
            d.table.to_csv(index=False).splitlines() if d.table is not None else [x.text for x in d.blocks] for d in (a[k], b[k])
        ]
        diff = [ln for ln in difflib.unified_diff(*lines, lineterm="", n=0) if ln[:1] in "+-" and ln[:3] not in ("+++", "---")]
        if diff:
            out.append({"doc": k, "change": "modified", "lines": diff[:limit], "more": max(0, len(diff) - limit)})
    return out


def staleness(case: EvalCase, new: LoadResult) -> list[str]:
    """Reasons why this case's expectation no longer matches the new documents (empty = still valid)."""
    if case.expected_refusal:
        return []
    if case.evidence:  # computed answers: compare the exact table cells they were derived from
        reasons = []
        for e in case.evidence:
            df = new.tables.get(e["table"])
            if df is None or e["key_column"] not in df.columns or e["column"] not in df.columns:
                reasons.append(f"table/column {e['table']}.{e['column']} no longer exists")
                continue
            row = df[df[e["key_column"]].astype(str) == e["key"]]
            if row.empty:
                reasons.append(f"record {e['key']} was removed")
            elif str(row.iloc[0][e["column"]]) != e["value"]:
                reasons.append(f"{e['key']} {e['column']} changed {e['value']} -> {row.iloc[0][e['column']]}")
        return reasons
    if case.type == "tool":
        return ["computed case from an older run without evidence: cannot be verified"]
    docs = {d.doc_id: d for d in new.documents}
    gone = [d for d in case.source_docs if d not in docs]
    if gone:
        return [f"source document removed: {', '.join(gone)}"]
    text = "\n".join(
        d.text if d.table is None else d.table.astype(str).to_string(index=False)
        for k, d in docs.items()
        if k in case.source_docs
    )
    return [f"fact no longer in {', '.join(case.source_docs)}: {f!r}" for f in case.key_facts if not fact_in(f, text)]


def run_regression(
    old_run: str | Path,
    new_docs: str | Path,
    out: str | Path,
    *,
    settings: Settings | None = None,
    client: LLMClient | None = None,
    workers: int = 4,
    on_event: Callable[[str], None] = print,
) -> dict:
    s = settings or get_settings()
    client = client or LLMClient(s)
    old_run, out = Path(old_run), Path(out)
    out.mkdir(parents=True, exist_ok=True)

    on_event("[1/4] loading old artifacts and new documents")
    manifest = _read(old_run / "manifest.json")
    req = Requirements.model_validate(_read(old_run / "02_requirements.json"))
    cases = [EvalCase.model_validate(c) for c in _read(old_run / "04_evals.json")["cases"]]
    iterations = [_read(p) for p in sorted(old_run.glob("05_iteration_*.json"))]
    before = {r["case_id"]: r for r in [i for i in iterations if i["accepted"]][-1]["results"]}
    old_def = load_agent_def(old_run / "agent.final.yaml")
    new = load_folder(new_docs)
    if not new.documents:
        raise SystemExit(f"No readable documents in {new_docs}")
    old_docs = Path(manifest["docs"])
    changes = document_changes(load_folder(old_docs), new) if old_docs.is_dir() else []

    on_event("[2/4] regenerating the agent from the new documents")
    duties = list(dict.fromkeys(req.must_answer_topics + req.ungrounded_topics))
    req = req.model_copy(update={"must_answer_topics": duties, "ungrounded_topics": [], "groundability": [], "assumptions": []})
    probe = old_def.model_copy(deep=True)
    index = build_index(new, probe, s)
    req = guard.run_guard(client, index, req, s.gen_model)
    agent_def = generator.build_agent(client, req, new, profile_corpus(new), s, s.gen_model)
    agent_def.version = old_def.version + 1
    agent_def.rules += [r for r in old_def.rules if r.added_in_iteration]
    agent_def.retrieval = old_def.retrieval.model_copy()
    save_agent_def(agent_def, out / "agent.regenerated.yaml")

    on_event(f"[3/4] running the old exam ({len(cases)} cases) against the regenerated agent")
    results = run_exam(Agent(agent_def, new, client, s, index=index), cases, client, s.judge_model, workers)

    rows = []
    for case, r in zip(cases, results):
        was = bool(before.get(case.id, {}).get("passed"))
        stale = staleness(case, new)
        if case.expected_refusal and not r.passed and _answerability(index, case.question) > 0.75:
            status = "recheck"
        elif stale:
            status = "stale"
        elif was and not r.passed:
            status = "regression"
        elif not was and r.passed:
            status = "fixed"
        else:
            status = "still passing" if r.passed else "still failing"
        rows.append(
            {
                "id": case.id,
                "type": case.type,
                "question": case.question,
                "status": status,
                "passed_before": was,
                "passed_now": r.passed,
                "reasons": stale,
                "answer": r.answer,
                "judge": r.judge_note,
            }
        )

    on_event("[4/4] writing the regression report")
    count = {
        k: sum(x["status"] == k for x in rows)
        for k in ("regression", "stale", "recheck", "fixed", "still failing", "still passing")
    }
    valid = [r for r, x in zip(results, rows) if x["status"] != "stale"]
    summary = {
        "old_run": str(old_run),
        "new_docs": str(new_docs),
        "counts": count,
        "old_passed": sum(x["passed_before"] for x in rows),
        "new_passed": sum(x["passed_now"] for x in rows),
        "total": len(rows),
        "score_on_valid_cases": score(valid),
        "valid_cases": len(valid),
        "document_changes": changes,
    }
    (out / "regression.json").write_text(json.dumps({**summary, "cases": rows}, indent=2, ensure_ascii=False), encoding="utf-8")

    L = [
        f"# Regression report: {old_run.name} against `{new_docs}`",
        "",
        f"**{count['regression']} real regression(s)**, {count['stale']} outdated test(s), {count['recheck']} to re-check, {count['fixed']} newly fixed.",
        f"Raw old exam: {summary['old_passed']}/{len(rows)} before, {summary['new_passed']}/{len(rows)} now. "
        f"On the {len(valid)} cases still valid for the new documents: {summary['score_on_valid_cases']:.0%}.",
        "",
        "## Document changes",
        "",
    ]
    for c in changes or [{"doc": "-", "change": "none detected (or old documents unavailable)"}]:
        L.append(f"- **{c['doc']}**: {c['change']}")
        L += [f"  - `{ln[:160]}`" for ln in c.get("lines", [])]
    for status, title in (
        ("regression", "Broke (facts still present)"),
        ("stale", "Outdated tests (documents changed)"),
        ("recheck", "Refusal cases the new documents may now answer"),
        ("still failing", "Still failing"),
    ):
        sel = [x for x in rows if x["status"] == status]
        if sel:
            L += ["", f"## {title}", ""]
            L += [
                f'- `{x["id"]}` ({x["type"]}) "{x["question"]}"  \n  now: {"pass" if x["passed_now"] else "fail"}; '
                f'{"; ".join(x["reasons"]) or x["judge"] or "-"}  \n  agent said: "{x["answer"][:160]}"'
                for x in sel
            ]
    L += ["", "Outdated cases should be regenerated with `forge run` on the new documents before trusting a new score.", ""]
    (out / "regression_report.md").write_text("\n".join(L), encoding="utf-8")
    on_event(f"done -> {out / 'regression_report.md'}")
    return summary
