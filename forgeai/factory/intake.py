"""Stage 1 - Intake interviewer.

Questions are generated from the document profile, then *audited deterministically*:
a question that doesn't mention anything that exists in the corpus (heading, column,
key term, file) is "generic" and is regenerated once with that feedback. The share of
document-grounded questions is stored in the requirements so the report can show it.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from forgeai.ingest.profiler import CorpusProfile
from forgeai.llm.client import LLMClient
from forgeai.llm.structured import generate_structured
from forgeai.prompts import render
from forgeai.schemas import QA, Answers, Question, QuestionSet, Requirements, RequirementsDraft

MAX_Q = 5
_W = re.compile(r"[a-z0-9]+")


def corpus_vocab(profile: CorpusProfile) -> set[str]:
    words: set[str] = set()
    for d in profile.docs:
        for s in [d.doc_id, *d.headings, *d.columns, *d.top_terms]:
            words |= {w for w in _W.findall(s.lower()) if len(w) > 3}
    return words


def grounded_terms(question: str, vocab: set[str]) -> list[str]:
    return sorted({w for w in _W.findall(question.lower()) if w in vocab})


def fallback_questions(profile: CorpusProfile) -> QuestionSet:
    """Used only when the model produces no usable question: questions assembled from what the documents contain, so
    the requester is still asked, and asked about this corpus."""
    out: list[Question] = []
    texts = [d for d in profile.docs if not d.columns]
    if len(profile.docs) >= 2:
        a, b = profile.docs[0].doc_id, profile.docs[1].doc_id
        out.append(
            Question(question=f"If {a} and {b} say different things, which should the assistant follow, or should it show both?")
        )
    for d in profile.docs:
        if d.columns:
            out.append(Question(question=f"Which of the columns in {d.doc_id} ({', '.join(d.columns[:6])}) may users ask about?"))
    for d in texts:
        if d.headings:
            heading = d.headings[-1]
            out.append(
                Question(
                    question=f"Should the assistant answer questions on '{heading}' in {d.doc_id}, and is any of it off limits?"
                )
            )
    for q in out:
        q.why = "built from the document profile because the model produced no usable question"
    return QuestionSet(questions=out[:MAX_Q])


def make_questions(client: LLMClient, brief: str, profile: CorpusProfile, model: str | None = None) -> tuple[QuestionSet, float]:
    vocab = corpus_vocab(profile)
    prompt = render("intake_questions", brief=brief, profile=profile.to_prompt(5000), max_questions=MAX_Q)

    def validate(qs: QuestionSet) -> None:
        if not 1 <= len(qs.questions) <= MAX_Q:
            raise ValueError(f"need 1..{MAX_Q} questions, got {len(qs.questions)}")

    fallback = QuestionSet(questions=[])
    res = generate_structured(
        client,
        QuestionSet,
        [{"role": "user", "content": prompt}],
        model=model,
        stage="intake",
        validator=validate,
        fallback=fallback,
    )
    qs = res.value if res.value.questions else fallback_questions(profile)
    for q in qs.questions:
        q.grounded_in = grounded_terms(q.question, vocab)
    generic = [q for q in qs.questions if not q.grounded_in]
    if generic and not res.used_fallback:
        feedback = (
            "These questions were generic (they mention nothing from the documents): "
            + " | ".join(q.question for q in generic)
            + ". Rewrite ALL questions so each names a real heading/term/column from the profile."
        )
        res2 = generate_structured(
            client,
            QuestionSet,
            [{"role": "user", "content": prompt}, {"role": "user", "content": feedback}],
            model=model,
            stage="intake",
            validator=validate,
            fallback=qs,
        )
        qs = res2.value
        for q in qs.questions:
            q.grounded_in = grounded_terms(q.question, vocab)
    qs.questions = qs.questions[:MAX_Q]
    share = (sum(1 for q in qs.questions if q.grounded_in) / len(qs.questions)) if qs.questions else 0.0
    return qs, share


def collect_answers(
    client: LLMClient,
    brief: str,
    profile: CorpusProfile,
    qs: QuestionSet,
    ask: Callable[[str], str] | None,
    model: str | None = None,
) -> list[QA]:
    """``ask`` is a callable (e.g. input) for a human; None => model proposes conservative defaults."""
    if ask is not None:
        out = []
        for q in qs.questions:
            a = ask(q.question).strip()
            out.append(
                QA(
                    question=q.question,
                    answer=a or "(no preference - use a sensible default)",
                    source="user" if a else "auto-default",
                )
            )
        return out
    if not qs.questions:
        return []
    numbered = "\n".join(f"{i}. {q.question}" for i, q in enumerate(qs.questions, 1))
    prompt = render("intake_autoanswer", brief=brief, profile=profile.to_prompt(3000), questions=numbered)
    n = len(qs.questions)

    def validate(a: Answers) -> None:
        if len(a.answers) != n:
            raise ValueError(f"need exactly {n} answers")

    res = generate_structured(
        client,
        Answers,
        [{"role": "user", "content": prompt}],
        model=model,
        stage="intake",
        validator=validate,
        fallback=Answers(answers=["(no preference - be conservative)"] * n),
    )
    return [QA(question=q.question, answer=a, source="auto-default") for q, a in zip(qs.questions, res.value.answers)]


def write_requirements(
    client: LLMClient, brief: str, profile: CorpusProfile, qa: list[QA], model: str | None = None
) -> Requirements:
    qa_text = "\n".join(f"Q: {x.question}\nA: {x.answer}" for x in qa) or "(none)"
    prompt = render("intake_requirements", brief=brief, profile=profile.to_prompt(4000), qa=qa_text)
    fb = RequirementsDraft(
        agent_name="document_assistant",
        purpose=brief[:200],
        audience="general users",
        tone="clear and concise",
        scope=brief[:300],
        must_answer_topics=[brief[:80]],
        must_refuse_topics=[],
    )
    res = generate_structured(
        client,
        RequirementsDraft,
        [{"role": "user", "content": prompt}],
        model=model,
        stage="intake",
        fallback=fb,
        max_tokens=1200,
    )
    assumptions = [f"{x.question} -> {x.answer}" for x in qa if x.source == "auto-default"]
    if res.used_fallback:
        assumptions.append("Requirements model output was invalid; deterministic fallback requirements were used.")
    d = res.value
    name = re.sub(r"[^a-z0-9_]+", "_", d.agent_name.lower()).strip("_") or "document_assistant"
    return Requirements(**{**d.model_dump(), "agent_name": name}, qa=qa, assumptions=assumptions, brief=brief)
