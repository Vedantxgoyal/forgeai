"""Hybrid retrieval: dense + BM25, fused with Reciprocal Rank Fusion, optional rerank.

Design (carried over from DocSage, rebuilt file-based for portability):
* RRF instead of weighted score blending - BM25 and cosine scores live on
  incompatible scales; fusing by rank avoids normalisation entirely.
* BM25 tokenisation keeps identifiers intact (``AB-1234``, ``ISO 9001``,
  ``HR-POL-07``) *and* their parts, so exact codes in catalogues and policies
  are found even when embeddings blur them.
* Every search returns a full trace (per-retriever ranks and scores, rerank
  score). The judge uses it to tell a retrieval miss from a generation failure,
  and the chat runner can show it as a transparency panel.
* ``mode`` / ``top_k`` / ``rerank`` are per-call so the optimizer can change
  retrieval parameters without rebuilding the index.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import numpy as np
from rank_bm25 import BM25Okapi

from forgeai.ingest.chunker import Chunk
from forgeai.retrieval.embed import Embedder, embed_query

log = logging.getLogger(__name__)

RRF_K = 60
_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[-_./][A-Za-z0-9]+)*")
_STOP = frozenset(
    "a an the of to in on for and or is are was were be been by with as at from that this it its "
    "what which who whom how when where why do does did can could should would will i my me we our "
    "you your they their there here not no".split()
)


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for tok in _TOKEN.findall(text.lower()):
        if tok in _STOP:
            continue
        out.append(tok)
        if re.search(r"[-_./]", tok):  # also index the parts of compound ids
            out.extend(p for p in re.split(r"[-_./]", tok) if p and p not in _STOP)
    return out


@dataclass
class Hit:
    chunk: Chunk
    score: float  # final score used for ordering (RRF or rerank)
    dense_rank: int | None = None
    dense_score: float | None = None
    bm25_rank: int | None = None
    bm25_score: float | None = None
    rerank_score: float | None = None

    def trace(self) -> dict:
        return {
            "chunk_id": self.chunk.chunk_id,
            "doc_id": self.chunk.doc_id,
            "score": round(self.score, 5),
            "dense_rank": self.dense_rank,
            "dense_score": None if self.dense_score is None else round(self.dense_score, 4),
            "bm25_rank": self.bm25_rank,
            "bm25_score": None if self.bm25_score is None else round(self.bm25_score, 4),
            "rerank_score": None if self.rerank_score is None else round(self.rerank_score, 4),
        }


@dataclass
class SearchParams:
    top_k: int = 5
    mode: str = "hybrid"  # dense | bm25 | hybrid
    rerank: bool = False
    candidates: int = 30  # pool size per retriever before fusion / rerank


class Reranker:
    """Cross-encoder reranker; ``available`` is False if the model can't load."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None
        self.available = True
        self.error: str | None = None

    def _load(self):
        if self._model is None and self.available:
            try:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(self.model_name, device="cpu")
            except Exception as exc:  # noqa: BLE001
                self.available = False
                self.error = str(exc)[:200]
                log.warning("reranker unavailable (%s); rerank requests become no-ops", self.error)

    def score(self, query: str, texts: list[str]) -> list[float] | None:
        self._load()
        if not self.available or self._model is None:
            return None
        return [float(s) for s in self._model.predict([(query, t) for t in texts])]


@dataclass
class HybridIndex:
    chunks: list[Chunk]
    embedder: Embedder
    reranker: Reranker | None = None
    _emb: np.ndarray = field(init=False, repr=False)
    _bm25: BM25Okapi | None = field(init=False, repr=False, default=None)

    def __post_init__(self):
        texts = [c.text for c in self.chunks]
        if texts:
            self.embedder.fit(texts)
            self._emb = self.embedder.embed(texts)
        else:
            self._emb = np.zeros((0, 1), dtype=np.float32)
        tokenized = [tokenize(t) or ["_empty_"] for t in texts]
        self._bm25 = BM25Okapi(tokenized) if tokenized else None
        self._by_id = {c.chunk_id: c for c in self.chunks}

    def __len__(self) -> int:
        return len(self.chunks)

    def get(self, chunk_id: str) -> Chunk | None:
        return self._by_id.get(chunk_id)

    # ------------------------------------------------------------------ #
    def _dense(self, query: str, n: int) -> list[tuple[int, float]]:
        if not len(self.chunks):
            return []
        q = embed_query(self.embedder, query)
        sims = self._emb @ q
        idx = np.argsort(-sims)[:n]
        return [(int(i), float(sims[i])) for i in idx]

    def _sparse(self, query: str, n: int) -> list[tuple[int, float]]:
        if self._bm25 is None:
            return []
        toks = tokenize(query)
        if not toks:
            return []
        scores = self._bm25.get_scores(toks)
        idx = np.argsort(-scores)[:n]
        return [(int(i), float(scores[i])) for i in idx if scores[i] > 0]

    def search(self, query: str, params: SearchParams | None = None) -> list[Hit]:
        p = params or SearchParams()
        top_k = max(1, min(p.top_k, len(self.chunks))) if self.chunks else 0
        if top_k == 0 or not query.strip():
            return []
        pool = max(p.candidates, top_k)

        dense = self._dense(query, pool) if p.mode in ("dense", "hybrid") else []
        sparse = self._sparse(query, pool) if p.mode in ("bm25", "hybrid") else []

        hits: dict[int, Hit] = {}
        for rank, (i, s) in enumerate(dense, start=1):
            h = hits.setdefault(i, Hit(self.chunks[i], 0.0))
            h.dense_rank, h.dense_score = rank, s
            h.score += 1.0 / (RRF_K + rank)
        for rank, (i, s) in enumerate(sparse, start=1):
            h = hits.setdefault(i, Hit(self.chunks[i], 0.0))
            h.bm25_rank, h.bm25_score = rank, s
            h.score += 1.0 / (RRF_K + rank)

        ranked = sorted(hits.values(), key=lambda h: (-h.score, h.chunk.chunk_id))

        if p.rerank and self.reranker is not None and ranked:
            pool_hits = ranked[: max(top_k * 4, 20)]
            scores = self.reranker.score(query, [h.chunk.text for h in pool_hits])
            if scores is not None:
                for h, s in zip(pool_hits, scores):
                    h.rerank_score = s
                    h.score = s
                ranked = sorted(pool_hits, key=lambda h: (-h.score, h.chunk.chunk_id))

        return ranked[:top_k]
