"""Fill-in-the-blank cases built without a model, used only when the model cannot produce enough verified cases.

A weak model, or a very small corpus, can leave the exam below its minimum size. Blanking the number of a quantity out of a
real sentence (the unit stays visible) gives a question whose answer is certainly in the documents. These cases are easier and more mechanical
than the model-written ones, so the report always states how many were used.
"""

from __future__ import annotations

import hashlib
import re

from forgeai.ingest.chunker import Chunk
from forgeai.schemas import EvalCase

_UNIT = (
    r"%|percent|working days?|calendar days?|days?|hours?|minutes?|weeks?|months?|years?|km/h|knots?|metres?|meters?|"
    r"kg|tonnes?|gross tonnage|litres?|units?"
)
_QUANTITY = re.compile(
    rf"(?:(?:USD|EUR|GBP|INR|SGD)\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?(?:{_UNIT})(?![\w/]))",
    re.I,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _title(chunk: Chunk) -> str:
    name = chunk.doc_id.replace("_", " ")
    return f"{name} ({chunk.section})" if chunk.section else name


def build_cloze_cases(chunks: list[Chunk], n: int) -> list[EvalCase]:
    """Up to ``n`` cases, taking one sentence per passage in turn so that no single passage dominates."""
    candidates: list[list[tuple[Chunk, str, str]]] = []
    for chunk in sorted(chunks, key=lambda c: c.chunk_id):
        if chunk.kind == "row":
            continue
        found = []
        for sentence in _SENTENCE.split(chunk.body.strip()):
            match = _QUANTITY.search(sentence)
            if match and 6 <= len(sentence.split()) <= 45:
                found.append((chunk, sentence.strip(), match.group(0).strip()))
        if found:
            candidates.append(found)

    cases: list[EvalCase] = []
    seen: set[str] = set()
    depth = 0
    while len(cases) < n and any(depth < len(c) for c in candidates):
        for group in candidates:
            if len(cases) >= n or depth >= len(group):
                continue
            chunk, sentence, fact = group[depth]
            if sentence in seen:
                continue
            seen.add(sentence)
            number = re.search(r"\d[\d,]*(?:\.\d+)?", fact).group(0)
            blanked = re.sub(rf"(?<![\d.,]){re.escape(number)}(?![\d]|[.,]\d)", "____", sentence)
            question = f'According to {_title(chunk)}, which number belongs in the blank: "{blanked}"'
            cases.append(
                EvalCase(
                    id="clz-" + hashlib.sha1(question.encode()).hexdigest()[:6],
                    type="answerable",
                    question=question,
                    reference_answer=sentence,
                    key_facts=[number],
                    source_docs=[chunk.doc_id],
                    gold_chunks=[chunk.chunk_id],
                )
            )
        depth += 1
    return cases
