"""Whole-factory smoke test with a scripted fake model (no network, no Ollama).

It proves the *plumbing*: every stage runs, artifacts are written, an unsupported topic is flagged,
a bad tool justification is dropped, refusal cases are verified, and the optimizer loop logs a
change. It says nothing about real model quality - the demo runs do that.
"""

import json
import re

import pytest

from forgeai.config import Settings
from forgeai.factory.baseline import compare_agents
from forgeai.factory.pipeline import run_factory
from forgeai.factory.regression import run_regression
from forgeai.llm.client import Completion, LLMClient

DOCS = "demos/hr_docs"


class FakeTransport:
    def complete(self, *, model, messages, temperature, max_tokens, json_mode, seed):
        user = messages[-1]["content"] if messages[-1]["role"] == "user" else messages[-2]["content"]
        return Completion(json.dumps(self.respond(user, messages)))

    def respond(self, user, messages):
        if "intake interviewer" in user:
            return {
                "questions": [
                    {"question": "Should the assistant cover the leave_policy annual leave carry forward rules?", "why": "leave"}
                ]
            }
        if "standing in for a busy client" in user:
            return {"answers": ["Yes, and be conservative."]}
        if "Write structured requirements" in user:
            return {
                "agent_name": "HR Helper",
                "purpose": "Answer HR questions",
                "audience": "shore staff",
                "tone": "polite",
                "scope": "HR leave, conduct and travel policies",
                "must_answer_topics": ["annual leave days", "sick leave certificate", "salary bands for engineers"],
                "must_refuse_topics": ["legal advice"],
            }
        if "Decide whether the TEXT" in user:
            topic = re.search(r"TOPIC: (.*)", user).group(1)
            return {"verdict": "no" if "salary" in topic else "yes", "note": "n/a"}
        if "Write the role prompt" in user:
            return {"role_prompt": "You are an HR assistant for shore staff.", "rules": ["Use a polite tone."]}
        if "Choose which tools" in user:
            return {"tools": [{"name": "weather", "justification": "the assistant must forecast ocean storms"}]}
        if (
            "write test questions for an assistant that answers ONLY" in user
            or "You write test questions for an assistant that answers ONLY" in user
        ):
            passage = user.split("):\n", 1)[1].split("\n\nAUDIENCE")[0]
            words = passage.split()
            return {
                "question": f"What does the policy say about {' '.join(words[2:5])}?",
                "answer": passage[:80],
                "key_facts": [" ".join(words[:2])],
            }
        if "COMBINING" in user.upper() and "PASSAGE A" in user:
            a = user.split("PASSAGE A")[1].split("):\n", 1)[1].split("\n\nPASSAGE B")[0].split()
            b = user.split("PASSAGE B")[1].split("):\n", 1)[1].split("\n\nWrite ONE")[0].split()
            return {
                "question": "How do the two documents relate on these topics?",
                "answer": "both",
                "key_facts": [" ".join(a[:2]), " ".join(b[:2])],
            }
        if "deliberately ambiguous" in user:
            a = user.split("PASSAGE A:\n")[1].split("\n\nPASSAGE B:")[0].split()
            b = user.split("PASSAGE B:\n")[1].split("\n\nFind something")[0].split()
            return {"question": "How long is the notice period here?", "facts_a": [" ".join(a[:3])], "facts_b": [" ".join(b[:3])]}
        if "Rewrite the role prompt" in user:
            return {"role_prompt": "You are an HR assistant for shore staff. Find the exact sentence first."}
        if "MUST REFUSE" in user:
            n = int(re.search(r"Write (\d+) questions", user).group(1))
            pool = [
                "What is the cricket score today?",
                "Which recipe makes the best pasta?",
                "Who won the football world cup?",
                "Explain quantum computing basics.",
                "How many bedrooms does the CEO house have?",
                "What is the salary band for engineers?",
                "What is the pension contribution percentage?",
                "Can you write python code for sorting?",
            ]
            return {"questions": pool[:n]}
        if "RULES:" in messages[0]["content"] and "CONTEXT:" in user:
            q = user.split("QUESTION:")[1].strip().lower()
            ctx = user.split("CONTEXT:")[1].split("QUESTION:")[0].strip()
            m = re.match(r"\[([^\]]+)\] (.*)", ctx, re.S)
            if (
                any(w in q for w in ("cricket", "pasta", "football", "quantum", "bedrooms", "salary", "pension", "python"))
                or not m
            ):
                return {
                    "action": "answer",
                    "answer": "I can't answer that from the provided documents.",
                    "citations": [],
                    "refused": True,
                }
            return {"action": "answer", "answer": m.group(2)[:400], "citations": [m.group(1)], "refused": False}
        if "strict grader" in user:
            n = len(re.findall(r"^\d+\. ", user.split("REQUIRED FACTS:")[1], re.M))
            return {"facts_present": [True] * n, "grounded": True}
        if "ONE new rule" in user:
            return {"rule": "Re-read every passage before deciding to refuse, and cite the passages you use."}
        raise AssertionError("unexpected prompt: " + user[:200])


def test_factory_end_to_end(tmp_path):
    s = Settings(
        use_cache=False, embed_backend="tfidf", cache_dir=tmp_path / "c", gen_model="fake", judge_model="fake", agent_model="fake"
    )
    client = LLMClient(s, transport=FakeTransport(), use_cache=False)
    out = tmp_path / "run"
    res = run_factory(
        "HR assistant that also explains salary bands.",
        DOCS,
        out,
        settings=s,
        client=client,
        n_cases=20,
        max_iters=2,
        workers=1,
        on_event=lambda m: None,
    )
    for f in (
        "00_brief.txt",
        "01_corpus_profile.json",
        "02_questions.json",
        "02_requirements.json",
        "03_agent.v1.yaml",
        "04_evals.json",
        "05_iteration_0.json",
        "agent.final.yaml",
        "changelog.json",
        "report.md",
        "manifest.json",
    ):
        assert (out / f).exists(), f
    req = res["requirements"]
    assert "salary bands for engineers" in req.ungrounded_topics  # groundability guard
    assert res["final"].tools == []  # fake tool justification was not in the brief -> dropped
    assert res["final"].dropped_tools and res["final"].dropped_tools[0]["tool"] == "weather"
    evals = json.loads((out / "04_evals.json").read_text(encoding="utf-8"))
    types = {c["type"] for c in evals["cases"]}
    assert {"answerable", "out_of_scope"} <= types and len(evals["cases"]) >= 15
    assert any(c["split"] == "holdout" for c in evals["cases"])
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "Scorecard per iteration" in report and "How trustworthy" in report and "100%" not in report.split("Verdict")[0]


def _client(tmp_path):
    s = Settings(
        use_cache=False, embed_backend="tfidf", cache_dir=tmp_path / "c", gen_model="fake", judge_model="fake", agent_model="fake"
    )
    return s, LLMClient(s, transport=FakeTransport(), use_cache=False)


def test_human_edit_tournament_regression_and_compare(tmp_path):
    s, client = _client(tmp_path)
    out = tmp_path / "run"

    def reviewer(req):
        return req.model_copy(update={"tone": "very formal", "must_refuse_topics": [*req.must_refuse_topics, "office gossip"]})

    run_factory(
        "HR assistant for shore staff.",
        DOCS,
        out,
        settings=s,
        client=client,
        n_cases=20,
        max_iters=1,
        workers=1,
        approve=reviewer,
        tournament=True,
        on_event=lambda m: None,
    )
    saved = json.loads((out / "02_requirements.json").read_text(encoding="utf-8"))
    assert saved["tone"] == "very formal" and (out / "02_requirements.generated.json").exists()
    contest = json.loads((out / "03_tournament.json").read_text(encoding="utf-8"))
    assert len(contest) == 3 and sum(c["winner"] for c in contest) == 1
    assert "Prompt tournament" in (out / "report.md").read_text(encoding="utf-8")

    summary = run_regression(
        out, "demos/hr_docs_v2", tmp_path / "reg", settings=s, client=client, workers=1, on_event=lambda m: None
    )
    assert summary["total"] >= 15 and (tmp_path / "reg" / "regression_report.md").exists()
    assert any(c["doc"] == "leave_policy" and c["change"] == "modified" for c in summary["document_changes"])
    same = run_regression(out, DOCS, tmp_path / "reg_same", settings=s, client=client, workers=1, on_event=lambda m: None)
    assert same["counts"]["stale"] == 0 and not same["document_changes"]

    text = compare_agents(out, "demos/handwritten/hr_agent.yaml", workers=1, client=client)
    assert "hand-written" in text and (out / "comparison.md").exists()


def test_rejected_requirements_stop_before_generation(tmp_path):
    s, client = _client(tmp_path)
    with pytest.raises(SystemExit):
        run_factory(
            "HR assistant.", DOCS, tmp_path / "run", settings=s, client=client, approve=lambda r: False, on_event=lambda m: None
        )
    assert not (tmp_path / "run" / "03_agent.v1.yaml").exists()
