"""Pluggable embedders with a guaranteed fallback chain.

``auto`` tries, in order:
  1. sentence-transformers (best quality, CPU-friendly ``bge-small``)
  2. Ollama ``/api/embed`` (no extra Python deps if Ollama is already running)
  3. TF-IDF + LSA (pure scikit-learn; always available, never fails)

The chosen backend is recorded in the run manifest so a score is always
attributable to the exact retrieval stack that produced it. Embeddings are
cached by (backend, text hash) - re-indexing an unchanged corpus is free.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Protocol

import numpy as np

from forgeai.config import Settings

log = logging.getLogger(__name__)


class Embedder(Protocol):
    name: str

    def fit(self, corpus: list[str]) -> None: ...
    def embed(self, texts: list[str]) -> np.ndarray: ...


def _l2norm(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


class _Cached:
    """Wraps an embedder with a content-hash disk cache."""

    def __init__(self, inner, cache_dir):
        import diskcache

        self.inner = inner
        self.name = inner.name
        self._cache = diskcache.Cache(str(cache_dir / "embeddings"))

    def fit(self, corpus):
        self.inner.fit(corpus)

    def embed(self, texts):
        keys = [hashlib.sha256(f"{self.name}\x00{t}".encode()).hexdigest() for t in texts]
        out: list[np.ndarray | None] = [self._cache.get(k) for k in keys]
        missing = [i for i, v in enumerate(out) if v is None]
        if missing:
            vecs = self.inner.embed([texts[i] for i in missing])
            for i, v in zip(missing, vecs):
                self._cache[keys[i]] = v
                out[i] = v
        return np.vstack(out) if out else np.zeros((0, 1), dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return embed_query(self.inner, text)


def embed_query(embedder, text: str) -> np.ndarray:
    """Query-side embedding (some models use an instruction prefix for queries)."""
    fn = getattr(embedder, "embed_query", None)
    return fn(text) if fn is not None else embedder.embed([text])[0]


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name, device="cpu")
        self.name = f"st:{model_name}"
        # bge models expect an instruction prefix on queries only.
        self._query_prefix = "Represent this sentence for searching relevant passages: " if "bge" in model_name else ""

    def fit(self, corpus):  # pretrained; nothing to fit
        pass

    def embed(self, texts):
        return _l2norm(self._model.encode(texts, batch_size=32, show_progress_bar=False))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([self._query_prefix + text])[0]


class OllamaEmbedder:
    def __init__(self, base_url: str, model: str, timeout: float = 60.0):
        import httpx

        self._http = httpx.Client(base_url=base_url, timeout=timeout)
        self._model = model
        self.name = f"ollama:{model}"
        # Probe once so 'auto' can fall through quickly if Ollama is absent.
        r = self._http.post("/api/embed", json={"model": model, "input": ["probe"]})
        r.raise_for_status()

    def fit(self, corpus):
        pass

    def embed(self, texts):
        vecs = []
        for i in range(0, len(texts), 64):
            r = self._http.post("/api/embed", json={"model": self._model, "input": texts[i:i + 64]})
            r.raise_for_status()
            vecs.extend(r.json()["embeddings"])
        return _l2norm(np.array(vecs))


class TfidfLsaEmbedder:
    """Corpus-fitted fallback. Not semantic, but deterministic and dependency-free.

    Small corpora use raw TF-IDF (exact term matching is better than a weak
    LSA projection); larger ones are projected to 256 dims with LSA.
    """

    name = "tfidf-lsa"

    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._vec = TfidfVectorizer(sublinear_tf=True, ngram_range=(1, 2), max_features=30000, stop_words="english")
        self._svd = None
        self._fitted = False

    def fit(self, corpus):
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer

        corpus = [t for t in corpus if t.strip()] or ["empty corpus placeholder"]
        try:
            m = self._vec.fit_transform(corpus)
        except ValueError:  # only stop words / symbols: fall back to character n-grams
            self._vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
            m = self._vec.fit_transform(corpus)
        n_comp = min(256, m.shape[0] - 1, m.shape[1] - 1)
        if m.shape[0] > 300 and n_comp >= 32:
            self._svd = TruncatedSVD(n_components=n_comp, random_state=0).fit(m)
        self._fitted = True

    def embed(self, texts):
        if not self._fitted:
            self.fit(texts)
        m = self._vec.transform(texts)
        dense = self._svd.transform(m) if self._svd is not None else m.toarray()
        return _l2norm(dense)


def get_embedder(settings: Settings, cache: bool = True) -> Embedder:
    """Return the best available embedder; never raises."""
    order = {
        "auto": ["st", "ollama", "tfidf"],
        "st": ["st", "tfidf"],
        "ollama": ["ollama", "tfidf"],
        "tfidf": ["tfidf"],
    }[settings.embed_backend]
    emb = None
    for backend in order:
        try:
            if backend == "st":
                emb = SentenceTransformerEmbedder(settings.st_model)
            elif backend == "ollama":
                emb = OllamaEmbedder(settings.ollama_native_url, settings.ollama_embed_model)
            else:
                emb = TfidfLsaEmbedder()
            break
        except Exception as exc:  # noqa: BLE001 - fall through to next backend
            log.info("embedder '%s' unavailable: %s", backend, str(exc)[:160])
    assert emb is not None
    log.info("using embedder %s", emb.name)
    # Corpus-fitted embedders must not be cached across corpora.
    if cache and settings.use_cache and not isinstance(emb, TfidfLsaEmbedder):
        return _Cached(emb, settings.cache_dir)
    return emb
