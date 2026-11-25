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


def resp(
    answer, refused=False, retrieved=("leave#1",), citations=("leave#1",), ctx="Shore staff accrue 24 days of paid annual leave."
):
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
    r = judge_case(NoLLM(), "m", case(), resp("I can't answer that.", refused=True), use_llm=False)
    assert r.failure == "wrong_refusal"
    r = judge_case(
        NoLLM(), "m", case(), resp("I can't answer that.", refused=True, ctx="unrelated text about travel"), use_llm=False
    )
    assert r.failure == "retrieval_miss"
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

    df = pd.DataFrame(
        {
            "part_no": ["A-1", "A-2", "A-3", "A-4"],
            "description": ["seal", "ring", "pin", "hose"],
            "unit_price_usd": [10.5, 20.0, 31.0, 45.5],
            "stock_qty": [3, 9, 4, 7],
        }
    )
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


def test_live_data_topics_are_served_by_tools_but_document_topics_are_not():
    from forgeai.factory.guard import live_tool_for

    assert live_tool_for("real-time weather check") == "weather"
    assert live_tool_for("current weather at the port") == "weather"
    assert live_tool_for("salary bands") == ""
    assert live_tool_for("weather limits compliance") == ""
    assert live_tool_for("current pension contribution") == ""


def test_small_corpus_still_yields_twenty_cases():
    """A handful of short passages must still produce the minimum exam size (several questions per passage)."""
    import itertools
    import json

    from forgeai.config import Settings
    from forgeai.factory.evalgen import generate_cases
    from forgeai.ingest.chunker import Chunk
    from forgeai.llm.client import Completion, LLMClient
    from forgeai.retrieval.embed import TfidfLsaEmbedder
    from forgeai.retrieval.index import HybridIndex
    from forgeai.schemas import Requirements

    topics = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]
    chunks = []
    for n, t in enumerate(topics):
        body = (
            f"The {t} rule requires notice {n + 11} hours before arrival and applies to every vessel calling at this berth today."
        )
        chunks.append(Chunk(chunk_id=f"d{n % 2}::{n}", doc_id=f"d{n % 2}", text=body, body=body))
    counter = itertools.count()

    class Fake:
        def complete(self, *, messages, **_):
            user = messages[-1]["content"]
            if any("PASSAGE A:" in m["content"] for m in messages):
                return Completion("{}")
            k = next(counter)
            if "MUST REFUSE" in user:
                return Completion(
                    json.dumps({"questions": [f"Who won the zebra{k}{i} chess trophy quickly?" for i in range(12)]})
                )
            word = topics[k % len(topics)]
            fact = next(c.body for c in chunks if c.body in user)
            digits = [w for w in fact.split() if w.isdigit()][0]
            return Completion(
                json.dumps(
                    {"question": f"What notice applies for item{k} {word}{k}?", "answer": "x", "key_facts": [f"{digits} hours"]}
                )
            )

    s = Settings(use_cache=False, embed_backend="tfidf")
    client = LLMClient(s, transport=Fake(), use_cache=False)
    req = Requirements(
        agent_name="a", purpose="p", audience="masters", tone="t", scope="port rules", must_answer_topics=["notice"]
    )
    cases, _ = generate_cases(client, HybridIndex(chunks, TfidfLsaEmbedder()), req, target=20)
    assert len(cases) >= 20


def test_quota_exhausted_model_falls_back_and_is_reported():
    from forgeai.config import Settings
    from forgeai.llm.client import Completion, LLMClient

    class T:
        calls: list = []

        def complete(self, *, model, **_):
            self.calls.append(model)
            if model == "big":
                raise RuntimeError("Rate limit reached on tokens per day (TPD). Please try again in 6m2s.")
            return Completion("hello")

    s = Settings(use_cache=False, fallback_models="small@local", transport_retries=0)
    c = LLMClient(s, transport=T(), use_cache=False)
    assert c.chat([{"role": "user", "content": "hi"}], model="big") == "hello"
    assert c.chat([{"role": "user", "content": "hi2"}], model="big") == "hello"
    assert T.calls == ["big", "small", "small"]
    assert c.substitutions == {"big -> small@local": 2}


def test_document_text_in_an_error_does_not_look_like_a_quota():
    from forgeai.llm.client import _UNAVAILABLE

    assert not _UNAVAILABLE.search("meals are USD 60 per day; the file does not exist in policy")


def test_contract_depends_on_tools_and_tone():
    from forgeai.factory.generator import output_contract
    from forgeai.schemas import Requirements

    req = Requirements(agent_name="a", purpose="p", audience="staff", tone="concise", scope="s", must_answer_topics=["t"])
    plain, tooled = output_contract(req, set()), output_contract(req, {"calculator", "csv_lookup"})
    assert plain["max_words"] == 90 and "calculations" not in plain
    assert {"calculations", "records"} <= set(tooled)


def test_asking_which_one_passes_an_ambiguous_case():
    amb = case(type="ambiguous", key_facts=["12 days", "24 days"], question="How many days do I get?")
    ok = judge_case(NoLLM(), "m", amb, resp("Do you mean annual leave or sick leave?"), use_llm=False)
    assert ok.passed
    bad = judge_case(NoLLM(), "m", amb, resp("You get 24 days.", ctx="12 days sick, 24 days annual"), use_llm=False)
    assert not bad.passed


def test_stale_cases_are_detected_from_changed_cells():
    import pandas as pd

    from forgeai.factory.regression import staleness
    from forgeai.factory.toolcases import build_tool_cases
    from forgeai.ingest.loaders import Document, LoadResult

    df = pd.DataFrame({"part_no": ["A-1", "A-2"], "description": ["seal", "ring"], "unit_price_usd": ["10.5", "20.0"]})
    case_ = build_tool_cases({"cat": df}, 1)[0]
    same = LoadResult([Document("cat", None, "table", table=df.copy())], [])
    assert staleness(case_, same) == []
    changed = df.assign(unit_price_usd=["99.0", "98.0"])
    assert "changed" in staleness(case_, LoadResult([Document("cat", None, "table", table=changed)], []))[0]


def test_account_id_is_redacted_from_errors():
    from forgeai.llm.client import _redact

    assert _redact("limit for organization `org_01abcdefghijklmnop` hit") == "limit for organization `org_REDACTED` hit"


def test_ambiguous_questions_must_fit_both_passages():
    from forgeai.factory.evalgen import _truly_ambiguous

    a = "Annual leave requests need 14 days notice."
    b = "Emergency leave of 3 days may be approved for a family emergency."
    assert _truly_ambiguous("How many days of leave?", a, b)
    assert not _truly_ambiguous("How many days of leave for a personal emergency?", a, b)  # only one passage fits
    assert not _truly_ambiguous("What is the maximum number of days in this situation?", a, b)


def test_shared_model_after_substitution_is_detected():
    from forgeai.factory.pipeline import _models_used

    subs = {"small -> big": 3, "judge -> big": 1}
    assert _models_used("small", subs) & _models_used("judge", subs) == {"big"}


def test_domain_rule_gate_catches_invented_currency_and_numbers():
    from forgeai.factory.generator import _invented_content

    corpus = "per diem is usd 60 per day"
    assert "GBP" in _invented_content("Figures are expressed in GBP.", corpus, [])
    assert "1.25" in _invented_content("Leave accrues at 1.25 days.", corpus, [])
    assert _invented_content("Quote the USD 60 allowance exactly.", corpus, []) == ""


class _Spent:
    def complete(self, **_):
        raise RuntimeError("The model `m` does not exist or you do not have access to it.")


def test_outages_are_never_turned_into_results():
    import pytest

    from forgeai.config import Settings
    from forgeai.factory.judge import _vote
    from forgeai.factory.optimizer import _new_rule
    from forgeai.llm.client import LLMClient, LLMUnavailable, RequestRejected, is_outage
    from forgeai.schemas import Requirements

    client = LLMClient(Settings(use_cache=False, transport_retries=0), transport=_Spent(), use_cache=False)
    req = Requirements(agent_name="a", purpose="p", audience="u", tone="t", scope="s", must_answer_topics=["x"])
    with pytest.raises(LLMUnavailable):
        _vote(client, "m", case(), resp("x"), ["24 days"])
    with pytest.raises(LLMUnavailable):
        _new_rule(client, "m", req, "hallucination", [], [], 1, "symptom")
    assert not is_outage(RequestRejected("context too long")) and not is_outage(ValueError("bad json"))


def test_fallbacks_never_cross_the_judge_agent_line():
    from forgeai.config import Settings
    from forgeai.llm.client import LLMClient

    s = Settings(
        use_cache=False, gen_model="a", agent_model="a", judge_model="j", fallback_models="b,j,j2", judge_fallback_models="j2,a,b"
    )
    client = LLMClient(s, transport=_Spent(), use_cache=False)
    assert client._chain("a") == ["a", "b", "j2"]
    assert client._chain("j") == ["j"]
    s = Settings(
        use_cache=False, gen_model="a", agent_model="a", judge_model="j", fallback_models="b", judge_fallback_models="j2"
    )
    client = LLMClient(s, transport=_Spent(), use_cache=False)
    assert client._chain("a") == ["a", "b"] and client._chain("j") == ["j", "j2"]


def test_client_waits_for_quota_when_allowed(monkeypatch):
    from forgeai.config import Settings
    from forgeai.llm import client as module

    clock = [1000.0]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    monkeypatch.setattr(module.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))

    class Refills:
        calls = 0

        def complete(self, **_):
            Refills.calls += 1
            if Refills.calls == 1:
                raise RuntimeError("Rate limit reached on tokens per day (TPD). Please try again in 4m0s.")
            return module.Completion("ok")

    s = Settings(use_cache=False, max_quota_wait_s=3600, transport_retries=0)
    assert module.LLMClient(s, transport=Refills(), use_cache=False).chat([{"role": "user", "content": "q"}], model="m") == "ok"
    assert Refills.calls == 2 and clock[0] >= 1240


def test_rerun_removes_only_files_of_the_previous_run(tmp_path):
    from forgeai.factory.pipeline import _clear_previous_run

    for name in ("05_iteration_3.json", "report.md", "NOTE.md", "my_notes.txt"):
        (tmp_path / name).write_text("x")
    _clear_previous_run(tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == ["my_notes.txt"]


def test_exam_reaches_its_floor_even_if_the_model_produces_nothing_usable():
    """A model that only ever returns junk must not leave the exam short: the rest is built from the documents."""
    from forgeai.config import Settings
    from forgeai.factory.evalgen import generate_cases
    from forgeai.ingest.chunker import Chunk
    from forgeai.llm.client import Completion, LLMClient
    from forgeai.retrieval.embed import TfidfLsaEmbedder
    from forgeai.retrieval.index import HybridIndex
    from forgeai.schemas import Requirements
    from forgeai.textutil import fact_in

    topics = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]
    chunks = []
    for n, t in enumerate(topics):
        body = " ".join(
            f"The {t} {kind} rule requires notice of {n * 3 + k + 2} hours before arrival at the berth."
            for k, kind in enumerate(["pilot", "cargo", "waste"])
        )
        chunks.append(Chunk(chunk_id=f"d{n % 2}::{n}", doc_id=f"d{n % 2}", text=body, body=body))

    class Junk:
        def complete(self, **_):
            return Completion("sorry, no idea")

    s = Settings(use_cache=False, embed_backend="tfidf", json_retries=0)
    req = Requirements(agent_name="a", purpose="p", audience="u", tone="t", scope="port rules", must_answer_topics=["notice"])
    cases, stats = generate_cases(
        LLMClient(s, transport=Junk(), use_cache=False), HybridIndex(chunks, TfidfLsaEmbedder()), req, target=20
    )
    assert len(cases) >= 20 and stats["cloze_fallback"] >= 20
    by_id = {c.chunk_id: c for c in chunks}
    for c in cases:
        assert fact_in(c.key_facts[0], by_id[c.gold_chunks[0]].body) and not fact_in(c.key_facts[0], c.question)
