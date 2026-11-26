"""Stage 4 - Eval generator.

Test cases come from the documents, never from the model's imagination, and every case is
*verified before it is allowed into the exam*:

* answerable / paraphrase: each key fact must occur verbatim (normalised) in the source chunk,
  otherwise the case is discarded (the LLM misquoted the document).
* multi_doc: facts must come from two different documents.
* out_of_scope / near_miss: the question must NOT be answerable - its content words may not be
  mostly covered by the single best-matching chunk. Otherwise it is discarded.

Gold chunk ids are kept so the optimizer can later tell a retrieval miss from a generation failure.
"""

from __future__ import annotations

import hashlib
import logging
import random
import re
from collections import defaultdict

from forgeai.factory.cloze import build_cloze_cases
from forgeai.factory.toolcases import build_tool_cases
from forgeai.ingest.chunker import Chunk
from forgeai.llm.client import LLMClient, is_outage
from forgeai.llm.structured import generate_structured
from forgeai.prompts import render
from forgeai.retrieval.index import HybridIndex, SearchParams
from forgeai.schemas import EvalCase, RawAmbiguous, RawQA, RawQuestions, Requirements
from forgeai.textutil import content_tokens, fact_in, norm

log = logging.getLogger(__name__)
MIN_CHUNK_WORDS = 15
MAX_FACT_WORDS = 12
_VAGUE = {"least", "most", "times", "time", "minimum", "maximum"}
MIN_CASES = 20
MAX_ROUNDS = 3
REFUSAL_ATTEMPTS = 2

STYLE = {
    "answerable": "Use the passage's own key terms in the question.",
    "paraphrase": "Ask it the way a non-expert would, avoiding the passage's exact terminology (use everyday synonyms) so keyword matching alone would struggle.",
}


def _eligible(chunks: list[Chunk]) -> list[Chunk]:
    return [c for c in chunks if len(c.body.split()) >= MIN_CHUNK_WORDS or c.kind == "row"]


def _stratified_sample(chunks: list[Chunk], n: int, seed: int) -> list[Chunk]:
    """Round-robin across documents so every document is examined; deterministic."""
    rng = random.Random(seed)
    by_doc: dict[str, list[Chunk]] = defaultdict(list)
    for c in _eligible(chunks):
        by_doc[c.doc_id].append(c)
    for v in by_doc.values():
        rng.shuffle(v)
    docs = sorted(by_doc)
    out: list[Chunk] = []
    while len(out) < n and any(by_doc.values()):
        for d in docs:
            if by_doc[d] and len(out) < n:
                out.append(by_doc[d].pop())
    return out


def _case_id(kind: str, question: str) -> str:
    return f"{kind[:3]}-{hashlib.sha1(question.encode()).hexdigest()[:6]}"


def _qa_for_chunk(client, model, chunk: Chunk, audience: str, style_key: str, avoid: list[str] | None = None) -> RawQA | None:
    prompt = render(
        "eval_qa",
        chunk_id=chunk.chunk_id,
        doc_id=chunk.doc_id,
        passage=chunk.body[:1800],
        audience=audience,
        style=STYLE[style_key]
        + (" Ask about a DIFFERENT detail than these existing questions: " + " | ".join(avoid) if avoid else ""),
    )
    try:
        res = generate_structured(
            client, RawQA, [{"role": "user", "content": prompt}], model=model, stage="evalgen", max_tokens=500, retries=1
        )
    except Exception as exc:
        if is_outage(exc):
            raise
        log.info("evalgen skipped chunk %s: %s", chunk.chunk_id, exc)
        return None
    return res.value


def _mentions_source_layout(question: str) -> bool:
    """A user cannot know about "passage A": such a question tests the generator's prompt, not the agent."""
    return re.search(r"\bpassages?\b", question, re.I) is not None


def _informative(fact: str) -> bool:
    """A "fact" such as "at least" or "all" would be found in almost any answer and proves nothing."""
    return any(ch.isdigit() for ch in fact) or bool(content_tokens(fact) - _VAGUE)


def _verify_facts(qa: RawQA, texts: list[str]) -> bool:
    """Facts must occur verbatim in the source AND carry information (not merely echo the question)."""
    joined = "\n".join(texts)
    if _mentions_source_layout(qa.question):
        return False
    qn = norm(qa.question)
    facts = [f for f in qa.key_facts if f.strip() and norm(f) not in qn and _informative(f)]
    if not facts or len(facts) < len(qa.key_facts) - 1 or len(qa.question.split()) < 4:
        return False
    qa.key_facts = facts
    return all(fact_in(f, joined) for f in facts)


_DANGLING = re.compile(r"\b(this|that|these|those) (situation|case|scenario|instance|one)\b|\bhere\b", re.I)
_GENERIC = {"many", "much", "maximum", "minimum", "long", "number", "allowed", "take", "taken", "get", "need", "limit", "time"}


def _truly_ambiguous(question: str, a: str, b: str) -> bool:
    """Both passages must be plausible targets: the question shares a subject with both and names nothing that
    appears in only one of them. A dangling reference ("this situation") makes a question meaningless, not ambiguous."""
    if _DANGLING.search(question):
        return False

    def words(text: str) -> set[str]:
        return {w.rstrip("s") for w in content_tokens(text)}

    asked = words(question) - {w.rstrip("s") for w in _GENERIC}
    in_a, in_b = words(a), words(b)
    return bool(asked & in_a & in_b) and not (asked & (in_a ^ in_b))


def _short_facts(qa: RawQA) -> None:
    """A whole sentence as a "fact" can only be matched by an LLM judge; short facts are checked deterministically."""
    long = [f for f in qa.key_facts if len(f.split()) > MAX_FACT_WORDS]
    if long:
        raise ValueError(
            f"each key fact must be a short phrase of at most {MAX_FACT_WORDS} words copied exactly; too long: {long[0]!r}"
        )


def _answerability(index: HybridIndex, question: str) -> float:
    """Coverage of the question's content words by the single best chunk (0..1)."""
    q = content_tokens(question)
    if not q:
        return 0.0
    hits = index.search(question, SearchParams(top_k=3, mode="hybrid"))
    return max((len(q & content_tokens(h.chunk.body)) / len(q) for h in hits), default=0.0)


def generate_cases(
    client: LLMClient,
    index: HybridIndex,
    req: Requirements,
    target: int = 24,
    seed: int = 7,
    model: str | None = None,
    tables: dict | None = None,
) -> tuple[list[EvalCase], dict]:
    stats = {"proposed": 0, "kept": 0, "dropped_unverified": 0, "dropped_answerable_refusal": 0, "by_type": {}}
    chunks = index.chunks
    multi_docs = len({c.doc_id for c in chunks}) >= 2
    n_refuse = max(4, round(target * 0.25))
    n_multi = max(2, round(target * 0.15)) if multi_docs else 0
    n_para = max(3, round(target * 0.15))
    tool_cases = build_tool_cases(tables or {}, max(3, round(target * 0.25)), seed)
    n_amb = 2 if len(_eligible(chunks)) >= 2 else 0
    n_ans = max(3, target - n_refuse - n_multi - n_para - n_amb - len(tool_cases))

    cases: list[EvalCase] = []
    seen_q: set[str] = set()

    def add(c: EvalCase) -> bool:
        key = " ".join(sorted(content_tokens(c.question)))
        if key in seen_q:
            return False
        seen_q.add(key)
        cases.append(c)
        return True

    pool = _stratified_sample(chunks, len(chunks), seed)
    asked: dict[str, list[str]] = defaultdict(list)
    queue = [(rnd, ch) for rnd in range(MAX_ROUNDS) for ch in pool]
    pi = 0

    def single(kind: str) -> bool:
        nonlocal pi
        while pi < len(queue):
            rnd, ch = queue[pi]
            pi += 1
            stats["proposed"] += 1
            qa = _qa_for_chunk(client, model, ch, req.audience, kind, asked[ch.chunk_id] if rnd else [])
            if qa is None or not _verify_facts(qa, [ch.body]):
                stats["dropped_unverified"] += 1
                continue
            asked[ch.chunk_id].append(qa.question.strip())
            if add(
                EvalCase(
                    id=_case_id(kind, qa.question),
                    type=kind,
                    question=qa.question.strip(),
                    reference_answer=qa.answer.strip(),
                    key_facts=[f.strip() for f in qa.key_facts],
                    source_docs=[ch.doc_id],
                    gold_chunks=[ch.chunk_id],
                )
            ):
                return True
        return False

    order = ["answerable"] * n_ans + ["paraphrase"] * n_para
    random.Random(seed + 1).shuffle(order)
    for kind in order:
        single(kind)

    if n_multi:
        base = [c for c in _stratified_sample(chunks, n_multi * 4, seed + 2)]
        made = 0
        for a in base:
            if made >= n_multi:
                break
            hits = [
                h.chunk
                for h in index.search(a.body[:300], SearchParams(top_k=10, mode="hybrid"))
                if h.chunk.doc_id != a.doc_id and len(h.chunk.body.split()) >= MIN_CHUNK_WORDS
            ]
            if not hits:
                continue
            b = hits[0]
            stats["proposed"] += 1
            prompt = render(
                "eval_multi",
                id_a=a.chunk_id,
                doc_a=a.doc_id,
                passage_a=a.body[:1200],
                id_b=b.chunk_id,
                doc_b=b.doc_id,
                passage_b=b.body[:1200],
            )
            try:
                qa = generate_structured(
                    client,
                    RawQA,
                    [{"role": "user", "content": prompt}],
                    model=model,
                    stage="evalgen",
                    max_tokens=600,
                    retries=1,
                    validator=_short_facts,
                ).value
            except Exception as exc:
                if is_outage(exc):
                    raise
                stats["dropped_unverified"] += 1
                continue
            in_a = any(fact_in(f, a.body) for f in qa.key_facts)
            in_b = any(fact_in(f, b.body) for f in qa.key_facts)
            if not (_verify_facts(qa, [a.body, b.body]) and in_a and in_b):
                stats["dropped_unverified"] += 1
                continue
            if add(
                EvalCase(
                    id=_case_id("multi", qa.question),
                    type="multi_doc",
                    question=qa.question.strip(),
                    reference_answer=qa.answer.strip(),
                    key_facts=[f.strip() for f in qa.key_facts],
                    source_docs=[a.doc_id, b.doc_id],
                    gold_chunks=[a.chunk_id, b.chunk_id],
                )
            ):
                made += 1

    made = 0
    for a in _stratified_sample(chunks, n_amb * 5, seed + 3):
        if made >= n_amb:
            break
        near = [
            h.chunk
            for h in index.search(a.body[:300], SearchParams(top_k=6, mode="hybrid"))
            if h.chunk.chunk_id != a.chunk_id and len(h.chunk.body.split()) >= MIN_CHUNK_WORDS
        ]
        if not near:
            continue
        b = near[0]
        stats["proposed"] += 1
        prompt = render("eval_ambiguous", passage_a=a.body[:1000], passage_b=b.body[:1000])
        try:
            raw = generate_structured(
                client,
                RawAmbiguous,
                [{"role": "user", "content": prompt}],
                model=model,
                stage="evalgen",
                max_tokens=500,
                retries=1,
            ).value
        except Exception as exc:
            if is_outage(exc):
                raise
            stats["dropped_unverified"] += 1
            continue
        fa, fb = raw.facts_a[0].strip(), raw.facts_b[0].strip()
        if (
            (
                not (fact_in(fa, a.body) and fact_in(fb, b.body) and norm(fa) != norm(fb))
                or norm(fa) in norm(raw.question)
                or norm(fb) in norm(raw.question)
            )
            or _mentions_source_layout(raw.question)
            or not _truly_ambiguous(raw.question, a.body, b.body)
        ):
            stats["dropped_unverified"] += 1
            continue
        if add(
            EvalCase(
                id=_case_id("ambig", raw.question),
                type="ambiguous",
                question=raw.question.strip(),
                reference_answer=f"Either ask which is meant, or give both: {fa} / {fb}",
                key_facts=[fa, fb],
                source_docs=sorted({a.doc_id, b.doc_id}),
                gold_chunks=[a.chunk_id, b.chunk_id],
            )
        ):
            made += 1

    terms = ", ".join(sorted({c.doc_id for c in chunks}))
    n_off = max(2, n_refuse // 2)
    n_near = n_refuse - n_off
    kinds = [
        (
            "out_of_scope",
            n_off,
            "Each question is clearly unrelated to the assistant's domain (e.g. sport, cooking, trivia, coding) or asks for something in TOPICS IT MUST REFUSE.",
        ),
        (
            "near_miss",
            n_near,
            "Each question sounds like it belongs to the assistant's domain and uses its vocabulary, but asks for a specific detail the documents do NOT contain (prefer the 'topics its documents do not cover' list if present). Do not ask about general knowledge.",
        ),
    ]
    for kind, n, instr in kinds:
        made = 0
        for attempt in range(REFUSAL_ATTEMPTS):
            if made >= n:
                break
            if attempt:
                instr = f"{instr} Write questions DIFFERENT from any you would have written before (attempt {attempt + 1})."
            prompt = render(
                "eval_refuse",
                scope=req.scope,
                refuse_topics="; ".join(req.must_refuse_topics) or "none listed",
                ungrounded="; ".join(req.ungrounded_topics) or "none identified",
                terms=terms,
                n=n * 2,
                kind_instructions=instr,
            )
            try:
                qs = generate_structured(
                    client,
                    RawQuestions,
                    [{"role": "user", "content": prompt}],
                    model=model,
                    stage="evalgen",
                    max_tokens=500,
                    retries=1,
                ).value.questions
            except Exception as exc:
                if is_outage(exc):
                    raise
                qs = []
            for q in qs:
                if made >= n:
                    break
                stats["proposed"] += 1
                cov = _answerability(index, q)
                limit = 0.45 if kind == "out_of_scope" else 0.75
                if cov > limit:
                    stats["dropped_answerable_refusal"] += 1
                    continue
                if add(EvalCase(id=_case_id(kind, q), type=kind, question=q.strip(), expected_refusal=True)):
                    made += 1

    for c in tool_cases:
        stats["proposed"] += 1
        cases.append(c)

    floor = min(target, MIN_CASES + 2)
    turn = 0
    while len(cases) < floor and single("paraphrase" if turn % 3 == 2 else "answerable"):
        turn += 1
    if len(cases) < floor:  # the model could not reach the minimum: build the rest from the documents directly
        for case_ in build_cloze_cases(chunks, len(chunks) * 3):
            if len(cases) >= floor:
                break
            if add(case_):
                stats["cloze_fallback"] = stats.get("cloze_fallback", 0) + 1

    by_type: dict[str, list[EvalCase]] = defaultdict(list)
    for c in cases:
        by_type[c.type].append(c)
    for lst in by_type.values():
        lst.sort(key=lambda c: c.id)
        for i, c in enumerate(lst):
            c.split = "holdout" if i % 10 in (2, 6, 9) else "dev"
    stats["kept"] = len(cases)
    stats["by_type"] = {t: len(v) for t, v in by_type.items()}
    return cases, stats
