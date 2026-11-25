"""Tests for the deterministic parts of the factory (no real LLM needed)."""

from forgeai.factory.judge import judge_case
from forgeai.factory.optimizer import _retrieval_step, _rule_is_clean
from forgeai.factory.report import wilson
from forgeai.schemas import AgentDef, AgentResponse, CaseResult, EvalCase
from forgeai.textutil import fact_in, looks_like_refusal, support_ratio


class NoLLM:
    """Judge client that always fails: proves deterministic checks stand alone."""

    class settings:
        json_retries = 0

    def chat(self, *a, **k):
        raise RuntimeError("no llm")


def case(**kw):
    base = dict(id="c1", type="answerable", question="How many days of annual leave?", key_facts=["24 days"], split="dev")
    base.update(kw)
    return EvalCase(**base)


def resp(answer, refused=False, retrieved=("leave#1",), citations=("leave#1",), ctx="Shore staff accrue 24 days of paid annual leave."):
    return AgentResponse(answer=answer, refused=refused, retrieved=list(retrieved), citations=list(citations), context_text=ctx)


def test_fact_matching_is_strict_on_numbers():
    assert fact_in("24 days", "You get 24 days of leave")
    assert not fact_in("24 days", "You get 14 days of leave")
    assert fact_in("USD 1,500", "the limit is usd 1500 per night")


def test_refusal_detection():
    assert looks_like_refusal("I can't answer that from the provided documents.")
    assert looks_like_refusal("")
    assert not looks_like_refusal("Staff get 24 days of annual leave.")


def test_support_ratio_flags_invented_numbers():
    ratio, bad = support_ratio("You get 30 days of leave", "Staff accrue 24 days of leave")
    assert "30" in bad


def test_judge_pass_and_hallucination():
    r = judge_case(NoLLM(), "m", case(), resp("Staff get 24 days of paid annual leave per year."), use_llm=False)
    assert r.passed and not r.failure
    r = judge_case(NoLLM(), "m", case(), resp("Staff get 30 days of paid annual leave per year."), use_llm=False)
    assert not r.passed and r.failure in ("hallucination", "prompt_defect", "retrieval_miss")


def test_judge_refusal_classes():
    # facts in context but agent refused -> wrong refusal
    r = judge_case(NoLLM(), "m", case(), resp("I can't answer that.", refused=True), use_llm=False)
    assert r.failure == "wrong_refusal"
    # facts not retrieved -> retrieval miss
    r = judge_case(NoLLM(), "m", case(), resp("I can't answer that.", refused=True, ctx="unrelated text about travel"), use_llm=False)
    assert r.failure == "retrieval_miss"
    # must-refuse question answered -> hallucination; refused -> pass
    oos = case(type="out_of_scope", expected_refusal=True, key_facts=[])
    assert judge_case(NoLLM(), "m", oos, resp("Paris is the capital."), use_llm=False).failure == "hallucination"
    assert judge_case(NoLLM(), "m", oos, resp("no", refused=True), use_llm=False).passed


def test_judge_missing_citation_is_prompt_defect():
    r = judge_case(NoLLM(), "m", case(), resp("Staff get 24 days of paid annual leave.", citations=()), use_llm=False)
    assert not r.passed and r.failure == "prompt_defect"


def test_rule_leakage_check():
    c = case()
    failing = [CaseResult(case_id="c1", type="answerable", split="dev", passed=False, refused=False, question=c.question)]
    assert _rule_is_clean("Always answer with exactly 24 days of leave for staff members.", [c], failing)
    assert not _rule_is_clean("Re-read every passage before you decide to refuse a question.", [c], failing)


def test_retrieval_ladder_is_ordered_and_finite():
    d, tried, seen = AgentDef(name="a", role_prompt="x"), set(), []
    while (s := _retrieval_step(d, tried, reranker_ok=False)) is not None:
        seen.append(s[1])
    assert len(seen) == 4 and "rerank" not in " ".join(seen).lower().split("enable")[0]
    assert d.retrieval.query_rewrite and d.retrieval.top_k == 12


def test_wilson_interval_brackets_estimate():
    lo, hi = wilson(18, 24)
    assert lo < 0.75 < hi and 0 <= lo and hi <= 1


def test_numbers_compared_by_value():
    from forgeai.textutil import numbers
    assert numbers("USD 2,675.00") == numbers("2675.0") == {"2675"}
    assert fact_in("2675.0", "costs USD 2,675.00 per unit")
    assert not fact_in("2675.0", "costs USD 2,576.00 per unit")


def test_tool_cases_are_computed_from_data():
    import pandas as pd
    from forgeai.factory.toolcases import build_tool_cases
    df = pd.DataFrame({"part_no": ["A-1", "A-2", "A-3", "A-4"], "description": ["seal", "ring", "pin", "hose"],
                       "unit_price_usd": [10.5, 20.0, 31.0, 45.5], "stock_qty": [3, 9, 4, 7]})
    cases = build_tool_cases({"cat": df}, 6)
    assert len(cases) >= 4 and all(c.type == "tool" and c.key_facts for c in cases)
    for c in cases:
        assert c.key_facts[0] == c.reference_answer.split("= ")[-1]


def test_bare_number_facts_match_whole_numbers_only():
    assert not fact_in("8", "we have 18 units")
    assert fact_in("8", "we have 8 units")


def test_native_tool_call_is_recovered_and_rate_hint_parsed():
    import json
    from forgeai.llm.client import _rate_limit_wait, _recover_native_tool_call

    class E(Exception):
        body = {"code": "tool_use_failed", "failed_generation": '{"name": "csv_lookup", "arguments": {"table": "t"}}'}

    assert json.loads(_recover_native_tool_call(E())) == {"action": "tool", "tool": "csv_lookup", "args": {"table": "t"}}
    assert _recover_native_tool_call(ValueError("x")) is None
    assert round(_rate_limit_wait(Exception("Please try again in 2m40.5s.")), 1) == 161.5
    assert _rate_limit_wait(Exception("try again in 850ms")) < 2
    assert _rate_limit_wait(Exception("boom")) is None


def test_list_markers_are_not_invented_numbers():
    answer = "It depends on the supplier:  1. OceanParts adds 12%.\n2. NordMarine adds 20%."
    _, bad = support_ratio(answer, "OceanParts 12% NordMarine 20%")
    assert not bad
    _, bad = support_ratio("The fee is 15.", "OceanParts 12%")
    assert bad == {"15"}
