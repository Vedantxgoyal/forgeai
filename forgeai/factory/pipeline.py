"""End-to-end orchestration: brief + folder -> run directory with every artifact.

Run layout (everything is committed for the demos):
  00_brief.txt  01_corpus_profile.json  02_questions.json  02_requirements.json
  03_agent.v1.yaml  04_evals.json  05_iteration_N.json  agent.final.yaml  changelog.json
  report.md  manifest.json
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from forgeai.agent.runtime import build_index, save_agent_def
from forgeai.config import Settings, get_settings
from forgeai.factory import evalgen, generator, guard, intake
from forgeai.factory.optimizer import optimize
from forgeai.factory.report import render_report
from forgeai.factory.tournament import run_tournament
from forgeai.ingest.chunker import suggest_params
from forgeai.ingest.loaders import load_folder
from forgeai.ingest.profiler import profile_corpus
from forgeai.llm.client import LLMClient
from forgeai.schemas import AgentDef, Requirements
from forgeai.tools import REGISTRY
from forgeai.tools.base import ToolContext

log = logging.getLogger(__name__)


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


_RUN_FILES = (
    "0[0-5]_*",
    "agent.final.yaml",
    "changelog.json",
    "report.md",
    "manifest.json",
    "comparison.md",
    "requirements.review.yaml",
    "NOTE.md",
    "docs_path.txt",
)


def _clear_previous_run(out: Path) -> None:
    """Re-using a run folder must not leave files from the earlier run behind: an old iteration file would be read
    as part of the new run. Only files the factory itself writes are removed."""
    for pattern in _RUN_FILES:
        for path in out.glob(pattern):
            if path.is_file():
                path.unlink()


def _models_used(wanted: str, substitutions: dict[str, int]) -> set[str]:
    """The configured model plus every stand-in that answered for it."""
    return {wanted} | {k.split(" -> ")[1] for k in substitutions if k.split(" -> ")[0] == wanted}


def run_factory(
    brief: str,
    docs: str | Path,
    out: str | Path,
    *,
    settings: Settings | None = None,
    client: LLMClient | None = None,
    ask: Callable[[str], str] | None = None,
    n_cases: int = 24,
    max_iters: int = 3,
    workers: int = 4,
    approve: Callable[[Requirements], Requirements | bool | None] | None = None,
    tournament: bool = False,
    token_budget: int = 0,
    max_seconds: float = 0,
    on_event: Callable[[str], None] = print,
) -> dict:
    """``approve`` is the human checkpoint: return the (possibly edited) Requirements or True to continue,
    False/None to stop. Budgets bound the improvement loop: it stops early instead of overrunning."""
    s = settings or get_settings()
    client = client or LLMClient(s)
    token_budget = token_budget or s.token_budget
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    _clear_previous_run(out)
    t0 = time.perf_counter()
    notes: list[str] = []

    (out / "00_brief.txt").write_text(brief, encoding="utf-8")
    on_event("[1/7] loading + profiling documents")
    load = load_folder(docs)
    if not load.documents:
        raise SystemExit(f"No readable documents in {docs}: {load.skipped}")
    profile = profile_corpus(load)
    _dump(out / "01_corpus_profile.json", profile.to_dict())
    for f, why in load.skipped:
        notes.append(f"skipped file {f}: {why}")

    on_event("[2/7] intake interview")
    qs, share = intake.make_questions(client, brief, profile, s.gen_model)
    _dump(out / "02_questions.json", {"grounded_share": share, **qs.model_dump()})
    qa = intake.collect_answers(client, brief, profile, qs, ask, s.gen_model)
    req = intake.write_requirements(client, brief, profile, qa, s.gen_model)
    notes.append(f"intake: {len(qs.questions)} questions, {share:.0%} reference real document terms")

    on_event("[3/7] groundability guard")
    cp = suggest_params(load.documents)
    probe = AgentDef(name="probe", role_prompt="probe")
    probe.retrieval.chunk_size, probe.retrieval.chunk_overlap = cp.chunk_size, cp.chunk_overlap
    index = build_index(load, probe, s)
    tctx = ToolContext(tables=load.tables)
    evidence = " ".join(f"{t.card.purpose} {t.card.needed_when}" for t in REGISTRY.values() if t.available(tctx)[0])
    evidence += " " + " ".join(c.replace("_", " ") for tb in load.tables.values() for c in tb.columns)
    req = guard.run_guard(client, index, req, s.gen_model, extra_evidence=evidence)
    _dump(out / "02_requirements.json", req.model_dump())

    if approve is not None:
        decision = approve(req)
        if not decision:
            raise SystemExit("Requirements rejected by the human reviewer; stopping before generation.")
        if isinstance(decision, Requirements) and decision.model_dump() != req.model_dump():
            _dump(out / "02_requirements.generated.json", req.model_dump())
            topics_changed = decision.must_answer_topics != req.must_answer_topics
            req = decision
            if topics_changed:
                req = req.model_copy(update={"ungrounded_topics": [], "groundability": []})
                req = guard.run_guard(client, index, req, s.gen_model, extra_evidence=evidence)
            _dump(out / "02_requirements.json", req.model_dump())
            notes.append("requirements were edited by a human reviewer (original kept in 02_requirements.generated.json)")
        else:
            notes.append("requirements approved by a human reviewer")

    on_event("[4/7] generating agent definition")
    d0 = generator.build_agent(client, req, load, profile, s, s.gen_model)
    save_agent_def(d0, out / "03_agent.v1.yaml")

    on_event("[5/7] generating verified eval cases")
    cases, gstats = evalgen.generate_cases(client, index, req, target=n_cases, seed=s.seed, model=s.gen_model, tables=load.tables)
    _dump(out / "04_evals.json", {"stats": gstats, "cases": [c.model_dump() for c in cases]})
    on_event(f"      {len(cases)} cases kept {gstats['by_type']} ({gstats['dropped_unverified']} unverified dropped)")
    if len(cases) < 20:
        notes.append(f"WARNING: only {len(cases)} verified cases could be generated (<20 target); score is less reliable.")

    on_event("[6/7] baseline exam + optimizer loop")
    agent_index = (
        build_index(load, d0, s)
        if (d0.retrieval.chunk_size, d0.retrieval.chunk_overlap) != (cp.chunk_size, cp.chunk_overlap)
        else index
    )
    contest: list[dict] = []
    if tournament:
        on_event("      prompt tournament on development cases")
        d0, contest = run_tournament(d0, load, req, cases, client, s, agent_index, workers)
        _dump(out / "03_tournament.json", contest)
        save_agent_def(d0, out / "03_agent.v1.yaml")
        on_event(f"      tournament winner: {next(r['candidate'] for r in contest if r['winner'])}")
    d_final, logs = optimize(
        d0,
        load,
        req,
        cases,
        client,
        s,
        base_index=agent_index,
        max_iters=max_iters,
        workers=workers,
        token_budget=token_budget,
        max_seconds=max(0.0, max_seconds - (time.perf_counter() - t0)) if max_seconds else 0,
        on_event=lambda m: on_event("      " + m),
    )
    for lg in logs:
        _dump(
            out / f"05_iteration_{lg.iteration}.json",
            {**{k: v for k, v in asdict(lg).items() if k != "results"}, "results": [r.model_dump() for r in lg.results]},
        )
    save_agent_def(d_final, out / "agent.final.yaml")
    _dump(
        out / "changelog.json",
        [
            {
                "iteration": lg.iteration,
                "accepted": lg.accepted,
                "note": lg.note,
                "score_before": lg.score_before,
                "score_after": lg.overall_score,
                "changes": [asdict(c) for c in lg.changes],
            }
            for lg in logs[1:]
        ],
    )

    on_event("[7/7] writing honest report")
    usage = client.meter.as_dict()
    models = {"gen": s.gen_model, "judge": s.judge_model, "agent": s.effective_agent_model}
    for swap, n in client.substitutions.items():
        notes.append(f"MODEL SUBSTITUTION: {swap} for {n} call(s) because the configured model was unavailable")
    shared = _models_used(s.effective_agent_model, client.substitutions) & _models_used(s.judge_model, client.substitutions)
    if client.substitutions and shared:
        notes.append(
            f"WARNING: after substitutions the agent and the judge were both served by {', '.join(sorted(shared))} for some calls; "
            "self-preference bias is possible and the configured judge/agent separation did not hold."
        )
    if token_budget or max_seconds:
        notes.append(
            f"budget: tokens {usage['_total']['total_tokens']}/{token_budget or 'unlimited'}, "
            f"time {time.perf_counter() - t0:.0f}s/{max_seconds or 'unlimited'}"
        )
    report = render_report(Path(docs).name, req, d0, d_final, cases, gstats, logs, usage, models, notes, contest)
    (out / "report.md").write_text(report, encoding="utf-8")
    _dump(
        out / "manifest.json",
        {
            "brief": brief,
            "docs": str(docs),
            "models": models,
            "usage": usage,
            "seconds": round(time.perf_counter() - t0, 1),
            "notes": notes,
            "seed": s.seed,
            "final_score": logs[-1].overall_score if logs[-1].accepted else None,
            "tools": [t.name for t in d_final.tools],
            "substitutions": client.substitutions,
        },
    )
    on_event(f"done in {time.perf_counter() - t0:.0f}s -> {out}")
    return {"out": str(out), "logs": logs, "final": d_final, "requirements": req}
