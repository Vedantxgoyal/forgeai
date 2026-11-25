from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from forgeai.llm.client import BudgetExceeded, LLMClient, LLMUnavailable
from forgeai.llm.structured import StructuredGenerationError, extract_json, generate_structured


class Questions(BaseModel):
    questions: list[str] = Field(max_length=5)


# --------------------------------------------------------------------------- #
# extract_json
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw, expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('Sure! Here it is:\n```json\n{"a": 1}\n```\nHope it helps', {"a": 1}),
        ('prefix {"a": [1, 2,], "b": True, "c": None,} suffix', {"a": [1, 2], "b": True, "c": None}),
        ('{"text": "braces } inside { strings"}', {"text": "braces } inside { strings"}),
        ("[1, 2, 3]", [1, 2, 3]),
    ],
)
def test_extract_json_variants(raw, expected):
    assert extract_json(raw) == expected


def test_extract_json_rejects_garbage():
    with pytest.raises(ValueError):
        extract_json("no json here at all")


# --------------------------------------------------------------------------- #
# generate_structured
# --------------------------------------------------------------------------- #
def test_structured_repairs_after_feedback(settings, fake):
    fake.push("not json", '{"questions": ["Who is the audience?"]}')
    client = LLMClient(settings, transport=fake)
    res = generate_structured(client, Questions, [{"role": "user", "content": "ask"}], stage="intake")
    assert res.value.questions == ["Who is the audience?"]
    assert res.attempts == 2 and not res.used_fallback
    # the repair turn must contain the error so the model can fix it
    assert "invalid" in fake.calls[1]["messages"][-1]["content"]


def test_structured_semantic_validator_triggers_retry(settings, fake):
    fake.push('{"questions": []}', '{"questions": ["q1"]}')
    client = LLMClient(settings, transport=fake)

    def non_empty(v: Questions):
        if not v.questions:
            raise ValueError("need at least one question")

    res = generate_structured(client, Questions, [{"role": "user", "content": "x"}], validator=non_empty)
    assert res.value.questions == ["q1"] and res.attempts == 2


def test_structured_uses_fallback_and_flags_it(settings, fake):
    fake.push("bad", "worse", "still bad")
    client = LLMClient(settings, transport=fake)
    res = generate_structured(
        client, Questions, [{"role": "user", "content": "x"}], fallback=lambda: Questions(questions=["default"])
    )
    assert res.used_fallback and res.value.questions == ["default"] and len(res.errors) == 3


def test_structured_raises_without_fallback(settings, fake):
    fake.push("bad", "bad", "bad")
    client = LLMClient(settings, transport=fake)
    with pytest.raises(StructuredGenerationError):
        generate_structured(client, Questions, [{"role": "user", "content": "x"}])


# --------------------------------------------------------------------------- #
# client: retries, cache, budget, metering
# --------------------------------------------------------------------------- #
class APIConnectionError(Exception):  # name matches the transient classifier
    pass


def test_transient_errors_are_retried(settings, fake, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    fake.push(APIConnectionError("down"), "ok")
    client = LLMClient(settings, transport=fake)
    assert client.chat([{"role": "user", "content": "hi"}], stage="t") == "ok"


def test_non_transient_error_fails_fast(settings, fake):
    fake.push(ValueError("bad request"))
    client = LLMClient(settings, transport=fake)
    with pytest.raises(LLMUnavailable):
        client.chat([{"role": "user", "content": "hi"}])
    assert len(fake.calls) == 1


def test_cache_makes_reruns_free(settings, fake):
    s = settings.model_copy(update={"use_cache": True})
    fake.push("first")
    client = LLMClient(s, transport=fake)
    msgs = [{"role": "user", "content": "same prompt"}]
    assert client.chat(msgs, stage="a") == "first"
    assert client.chat(msgs, stage="a") == "first"  # no second scripted response needed
    assert client.meter.stages["a"].cache_hits == 1


def test_budget_stops_new_calls(settings, fake):
    s = settings.model_copy(update={"token_budget": 10})
    fake.push("one", "two")
    client = LLMClient(s, transport=fake)
    client.chat([{"role": "user", "content": "a"}])  # uses 15 tokens
    with pytest.raises(BudgetExceeded):
        client.chat([{"role": "user", "content": "b"}])


def test_meter_tracks_stages(settings, fake):
    fake.push("x", "y")
    client = LLMClient(settings, transport=fake)
    client.chat([{"role": "user", "content": "1"}], stage="intake")
    client.chat([{"role": "user", "content": "2"}], stage="judge")
    d = client.meter.as_dict()
    assert d["intake"]["calls"] == 1 and d["judge"]["calls"] == 1 and d["_total"]["total_tokens"] == 30
