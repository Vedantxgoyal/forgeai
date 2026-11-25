"""Stage 6 - Critic-optimizer loop (max 3 iterations).

The critic is mostly *deterministic*: the judge already says which failure class each case
falls in and why (see judge.py). The optimizer then applies the SMALLEST change that targets
each class, instead of regenerating the agent:

  retrieval_miss -> next untried step of a retrieval ladder (top_k, query rewrite, rerank, smaller chunks)
  wrong_refusal  -> one new prompt rule about answering when context is sufficient
  hallucination  -> one new grounding / scope-boundary rule
  prompt_defect  -> one new completeness / citation rule

Guard-rails against fooling ourselves:
* Fixes are chosen from the DEV split only; a hold-out split (never inspected by the critic) is
  scored every round, so over-fitting shows up as a gap in the report.
* A new rule is rejected if it leaks test content (contains a key fact, or copies a failing question).
* An iteration is rolled back when it lowers the dev score or hold-out score by more than one case.
* Everything is logged: what changed, why, which cases it targeted, score before/after.
"""

from __future__ import annotations

import copy
import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

from pydantic import BaseModel

from forgeai.agent.runtime import Agent
from forgeai.config import Settings
from forgeai.factory.judge import judge_case
from forgeai.ingest.loaders import LoadResult
from forgeai.llm.client import LLMClient
from forgeai.llm.structured import generate_structured
from forgeai.prompts import render
from forgeai.retrieval.index import HybridIndex
from forgeai.agent.runtime import build_index
from forgeai.schemas import AgentDef, CaseResult, EvalCase, Requirements, Rule
from forgeai.textutil import content_tokens, fact_in, norm

log = logging.getLogger(__name__)

MEANING = {
    "wrong_refusal": "the assistant refused even though the CONTEXT it was given contained the answer",
    "hallucination": "the assistant stated things not supported by the CONTEXT, or answered a question it should have declined",
    "prompt_defect": "the assistant had the right context but its answer was incomplete, omitted required details, or lacked valid citations",
}
FALLBACK_RULES = {
    "wrong_refusal": "Before refusing, re-read every CONTEXT passage; if any passage states the answer, even in different wording, answer from it and cite it.",
    "hallucination": "Every sentence of your answer must be directly supported by a CONTEXT passage; if a detail is not written there, leave it out or refuse.",
    "prompt_defect": "State every relevant condition, number and exception found in the CONTEXT passages you cite, and always list the cited chunk ids in \"citations\".",
}


class _Rule(BaseModel):
    rule: str


@dataclass
class Change:
    category: str
    kind: str  # retrieval | rule | none
    detail: str
    addresses: list[str] = field(default_factory=list)
    rejected_reason: str = ""


@dataclass
class IterationLog:
    iteration: int
    dev_score: float
    holdout_score: float
    overall_score: float
    n_pass: int
    n_total: int
    failures_by_class: dict
    changes: list[Change]
    accepted: bool
    note: str = ""
    score_before: float | None = None
    by_type: dict = field(default_factory=dict)
    results: list[CaseResult] = field(default_factory=list)
    agent_version: int = 1
    seconds: float = 0.0


def score(results: list[CaseResult], split: str | None = None) -> float:
    rs = [r for r in results if split is None or r.split == split]
    return round(sum(r.passed for r in rs) / len(rs), 4) if rs else 0.0


def run_exam(agent: Agent, cases: list[EvalCase], client: LLMClient, judge_model: str, workers: int = 4, use_llm_judge: bool = True) -> list[CaseResult]:
    def one(c: EvalCase) -> CaseResult:
        resp = agent.ask(c.question)
        r = judge_case(client, judge_model, c, resp, use_llm=use_llm_judge)
        if resp.error:
            r.judge_note = (r.judge_note + "; " if r.judge_note else "") + f"agent error: {resp.error}"
        return r

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(one, cases))


# ---------------------------------------------------------------------- #
def _rule_is_clean(rule: str, cases: list[EvalCase], failing: list[CaseResult]) -> str:
    """Return '' if OK, else the reason the rule is rejected."""
    if not 6 <= len(rule.split()) <= 45:
        return "length out of range"
    low = norm(rule)
    for c in cases:
        for f in c.key_facts:
            nf = norm(f)
            if len(nf) >= 4 and nf in low:
                return f"leaks key fact {f!r}"
    rt = content_tokens(rule)
    for r in failing:
        qt = content_tokens(r.question)
        if qt and len(rt & qt) / len(qt) >= 0.7:
            return "copies a failing test question"
    if re.search(r"\b(ignore|outside knowledge|general knowledge|guess)\b", low) and not re.search(r"\b(never|not|don'?t|without)\b", low):
        return "weakens grounding"
    return ""


def _new_rule(client: LLMClient, model: str, req: Requirements, category: str, failing: list[CaseResult],
              all_cases: list[EvalCase], n: int, symptoms_override: str = "") -> tuple[str, str]:
    kinds = sorted({r.type for r in failing})
    symptoms = symptoms_override or (f"{len(failing)} failing question(s) of type(s): {', '.join(kinds)}. "
                                     "Examples of the wording (not to be copied): " + " | ".join(r.question[:90] for r in failing[:3]))
    prompt = render("fix_rule", category=category, scope=req.scope, meaning=MEANING[category], symptoms=f"{symptoms} (attempt {n})")
    try:
        res = generate_structured(client, _Rule, [{"role": "user", "content": prompt}], model=model, stage="optimize", max_tokens=200, retries=1)
        cand = res.value.rule.strip()
    except Exception:  # noqa: BLE001
        cand = ""
    why = _rule_is_clean(cand, all_cases, failing) if cand else "LLM produced no valid rule"
    if why:
        return FALLBACK_RULES[category], f"LLM rule rejected ({why}); used vetted template rule"
    return cand, "LLM-written rule passed leakage checks"


def _retrieval_step(d: AgentDef, tried: set[str], reranker_ok: bool) -> tuple[AgentDef, str] | None:
    r = d.retrieval
    ladder = [
        ("top_k_8", lambda: setattr(r, "top_k", max(r.top_k, 8)), f"top_k {r.top_k} -> {max(r.top_k, 8)} (answer may sit just below the cut-off)"),
        ("rewrite", lambda: setattr(r, "query_rewrite", True), "enable LLM query rewrite (user wording differs from document vocabulary)"),
        ("rerank", lambda: setattr(r, "rerank", True), "enable cross-encoder reranking over the candidate pool"),
        ("smaller_chunks", lambda: (setattr(r, "chunk_size", max(60, int(r.chunk_size * 0.6))), setattr(r, "chunk_overlap", max(10, int(r.chunk_overlap * 0.6)))),
         f"chunk size {r.chunk_size} -> {max(60, int(r.chunk_size * 0.6))} words (answer diluted inside large chunks)"),
        ("top_k_12", lambda: setattr(r, "top_k", 12), "top_k -> 12"),
    ]
    for key, fn, desc in ladder:
        if key in tried or (key == "rerank" and not reranker_ok):
            continue
        tried.add(key)
        fn()
        return d, desc
    return None


def optimize(d0: AgentDef, load: LoadResult, req: Requirements, cases: list[EvalCase], client: LLMClient, settings: Settings,
             base_results: list[CaseResult] | None = None, base_index: HybridIndex | None = None, max_iters: int = 3,
             workers: int = 4, on_event=lambda msg: None) -> tuple[AgentDef, list[IterationLog]]:
    import time

    judge_model = settings.judge_model
    index = base_index or build_index(load, d0, settings)
    reranker_ok = False
    if index.reranker is not None:
        reranker_ok = index.reranker.score("test", ["test"]) is not None

    def exam(d: AgentDef, idx: HybridIndex) -> list[CaseResult]:
        return run_exam(Agent(d, load, client, settings, index=idx), cases, client, judge_model, workers)

    t0 = time.perf_counter()
    on_event("baseline exam")
    best_d, best_idx = d0, index
    best_res = base_results or exam(d0, index)
    logs: list[IterationLog] = []

    def mk(i, d, res, changes, accepted, note="", before=None) -> IterationLog:
        by_type: dict = {}
        for t in sorted({r.type for r in res}):
            rt = [r for r in res if r.type == t]
            by_type[t] = f"{sum(r.passed for r in rt)}/{len(rt)}"
        fails: dict = defaultdict(int)
        for r in res:
            if not r.passed:
                fails[r.failure or "unclassified"] += 1
        return IterationLog(i, score(res, "dev"), score(res, "holdout"), score(res), sum(r.passed for r in res), len(res), dict(fails),
                            changes, accepted, note, before, by_type, res, d.version, round(time.perf_counter() - t0, 1))

    logs.append(mk(0, d0, best_res, [], True, "baseline (as generated)"))
    tried: set[str] = set()
    rejected_rules: set[str] = set()
    case_by_id = {c.id: c for c in cases}

    for it in range(1, max_iters + 1):
        dev_fail = [r for r in best_res if not r.passed and r.split == "dev"]
        if not dev_fail:
            on_event("no dev failures left; stopping early")
            logs[-1].note += " | stopped: no dev failures remain"
            break
        groups: dict[str, list[CaseResult]] = defaultdict(list)
        for r in dev_fail:
            groups[r.failure or "prompt_defect"].append(r)
        on_event(f"iteration {it}: dev failures {dict((k, len(v)) for k, v in groups.items())}")

        cand = copy.deepcopy(best_d)
        cand.version = best_d.version + 1
        changes: list[Change] = []
        rebuild = False
        for cat in ("retrieval_miss", "wrong_refusal", "hallucination", "prompt_defect"):
            fl = groups.get(cat)
            if not fl:
                continue
            ids = [r.case_id for r in fl]
            if cat == "retrieval_miss":
                before = (cand.retrieval.chunk_size, cand.retrieval.chunk_overlap)
                step = _retrieval_step(cand, tried, reranker_ok)
                if step is None:
                    changes.append(Change(cat, "none", "retrieval ladder exhausted; remaining misses reported as unresolved", ids))
                    continue
                rebuild |= before != (cand.retrieval.chunk_size, cand.retrieval.chunk_overlap)
                changes.append(Change(cat, "retrieval", step[1], ids))
            else:
                if cat == "hallucination" and any(case_by_id[i].expected_refusal for i in ids):
                    refuse_ids = [r for r in fl if case_by_id[r.case_id].expected_refusal]
                    sym = (f"{len(refuse_ids)} question(s) the assistant should have declined were answered from general knowledge or loosely related text. "
                           f"Topics it must decline: {'; '.join(req.must_refuse_topics) or 'anything not in the documents'}.")
                elif cat == "prompt_defect" and all(case_by_id[i].type == "tool" for i in ids):
                    sym = ("Questions needing a record lookup and/or arithmetic returned wrong or no values. Available tools: "
                           + ", ".join(t.name for t in cand.tools) + ". Say when and how to call them.")
                else:
                    sym = ""
                text, how = _new_rule(client, settings.gen_model, req, cat, fl, cases, it, sym)
                if norm(text) in rejected_rules:  # same rule was already tried and rolled back
                    text, how = FALLBACK_RULES[cat], "previous LLM rule was rolled back; tried vetted template rule instead"
                if norm(text) in rejected_rules:
                    changes.append(Change(cat, "none", "no new rule available: every candidate was already tried and rolled back", ids))
                    continue
                rid = f"f{it}{cat[0]}"
                cand.rules.append(Rule(id=rid, text=text, added_in_iteration=it, category=cat, reason=how))
                changes.append(Change(cat, "rule", f"[{rid}] {text}  ({how})", ids))
        if all(c.kind == "none" for c in changes):
            logs[-1].note += " | stopped: no further targeted fix available"
            on_event("no further fixes available")
            break

        cand_idx = build_index(load, cand, settings) if rebuild else best_idx
        res = exam(cand, cand_idx)
        d_new, d_old = score(res, "dev"), score(best_res, "dev")
        h_new, h_old = score(res, "holdout"), score(best_res, "holdout")
        n_h = max(1, sum(1 for r in res if r.split == "holdout"))
        regress = d_new < d_old or (h_new < h_old - 1.5 / n_h)
        accepted = not regress and (d_new > d_old or h_new > h_old)  # a change must earn its place
        note = ("accepted" if accepted else
                f"rolled back: dev {d_old:.2f}->{d_new:.2f}, holdout {h_old:.2f}->{h_new:.2f}" if regress else "no improvement; kept previous agent")
        logs.append(mk(it, cand, res, changes, accepted, note, before=score(best_res)))
        on_event(f"iteration {it}: dev {d_old:.2f}->{d_new:.2f} holdout {h_old:.2f}->{h_new:.2f} ({'accepted' if accepted else 'rolled back'})")
        if accepted:
            best_d, best_res, best_idx = cand, res, cand_idx
        else:
            rejected_rules |= {norm(r.text) for r in cand.rules if r.added_in_iteration == it}
    return best_d, logs
