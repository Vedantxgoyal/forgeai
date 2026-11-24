"""Section-aware chunking with overlap, plus row-level chunks for tables.

Chunk sizes are measured in words (a stable, model-agnostic proxy for tokens;
~1.3 tokens/word for English). Each chunk is prefixed with its document and
section title so a retrieved chunk is self-describing - this measurably helps
both BM25 and dense retrieval on policy-style documents, and lets the judge
verify citations without re-opening the source.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from forgeai.ingest.loaders import Block, Document

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    text: str  # what gets embedded / shown to the agent (with header)
    body: str  # raw content without header (used for fact verification)
    section: str = ""
    page: int | None = None
    kind: str = "text"  # text | row
    row_index: int | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in vars(self).items()}


@dataclass(frozen=True)
class ChunkParams:
    chunk_size: int = 220  # words
    chunk_overlap: int = 40  # words

    def __post_init__(self):
        if self.chunk_size < 30:
            raise ValueError("chunk_size must be >= 30 words")
        if not 0 <= self.chunk_overlap < self.chunk_size // 2:
            raise ValueError("chunk_overlap must be in [0, chunk_size/2)")


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #
@dataclass
class _Section:
    title: str
    blocks: list[Block]


def _sections(doc: Document) -> list[_Section]:
    sections: list[_Section] = [_Section(title="", blocks=[])]
    for b in doc.blocks:
        if b.is_heading:
            sections.append(_Section(title=b.text, blocks=[]))
        else:
            sections[-1].blocks.append(b)
    return [s for s in sections if s.blocks]


def _split_long(text: str, max_words: int) -> list[str]:
    """Split an over-long paragraph by sentence, then hard-split by words."""
    out: list[str] = []
    for sent in _SENT_SPLIT.split(text):
        words = sent.split()
        while len(words) > max_words:
            out.append(" ".join(words[:max_words]))
            words = words[max_words:]
        if words:
            out.append(" ".join(words))
    return out


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def chunk_document(doc: Document, params: ChunkParams) -> list[Chunk]:
    if doc.table is not None:
        return _chunk_table(doc)

    chunks: list[Chunk] = []
    for sec in _sections(doc):
        # Units = (text, page) at sentence-or-paragraph granularity.
        units: list[tuple[str, int | None]] = []
        for b in sec.blocks:
            if len(b.text.split()) > params.chunk_size:
                units += [(s, b.page) for s in _split_long(b.text, params.chunk_size)]
            else:
                units.append((b.text, b.page))

        buf: list[tuple[str, int | None]] = []
        buf_words = 0
        for text, page in units:
            n = len(text.split())
            if buf and buf_words + n > params.chunk_size:
                chunks.append(_make_chunk(doc, sec.title, buf, len(chunks)))
                buf, buf_words = _overlap_tail(buf, params.chunk_overlap)
            buf.append((text, page))
            buf_words += n
        if buf:
            chunks.append(_make_chunk(doc, sec.title, buf, len(chunks)))
    return chunks


def chunk_documents(docs: list[Document], params: ChunkParams) -> list[Chunk]:
    out: list[Chunk] = []
    for d in docs:
        out.extend(chunk_document(d, params))
    return out


def suggest_params(docs: list[Document]) -> ChunkParams:
    """Data-driven starting point: size chunks to the corpus' natural sections.

    Short-section corpora (FAQs, policies with many clauses) get small chunks so
    one chunk ~ one rule; long narrative sections get larger chunks.
    """
    lengths = [
        sum(len(b.text.split()) for b in s.blocks)
        for d in docs
        if d.table is None
        for s in _sections(d)
    ]
    if not lengths:
        return ChunkParams()
    median = statistics.median(lengths)
    size = int(min(400, max(120, round(median * 1.2 / 20) * 20)))
    return ChunkParams(chunk_size=size, chunk_overlap=max(10, int(size * 0.15)))


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #
def _overlap_tail(buf: list[tuple[str, int | None]], overlap_words: int):
    if overlap_words <= 0:
        return [], 0
    words: list[str] = []
    page = buf[-1][1]
    for text, p in reversed(buf):
        words = text.split() + words
        page = p
        if len(words) >= overlap_words:
            break
    words = words[-overlap_words:]
    return [(" ".join(words), page)], len(words)


def _header(doc: Document, section: str) -> str:
    return f"[{doc.doc_id}{' > ' + section if section else ''}]"


def _make_chunk(doc: Document, section: str, buf, idx: int) -> Chunk:
    body = " ".join(t for t, _ in buf).strip()
    page = next((p for _, p in buf if p is not None), None)
    return Chunk(
        chunk_id=f"{doc.doc_id}::{idx:04d}",
        doc_id=doc.doc_id,
        text=f"{_header(doc, section)}\n{body}",
        body=body,
        section=section,
        page=page,
    )


def _chunk_table(doc: Document) -> list[Chunk]:
    assert doc.table is not None
    df = doc.table
    cols = list(df.columns)
    chunks: list[Chunk] = []
    for i, row in enumerate(df.itertuples(index=False, name=None)):
        pairs = [f"{c}: {v}" for c, v in zip(cols, row) if str(v).strip()]
        body = "; ".join(pairs)
        chunks.append(
            Chunk(
                chunk_id=f"{doc.doc_id}::r{i:05d}",
                doc_id=doc.doc_id,
                text=f"[{doc.doc_id} row {i + 1}]\n{body}",
                body=body,
                kind="row",
                row_index=i,
            )
        )
    return chunks
