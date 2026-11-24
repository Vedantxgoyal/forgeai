"""Deterministic corpus profile - what the documents actually contain.

The intake interviewer and groundability guard reason over this profile rather
than over raw documents, which keeps prompts small enough for a 7B model and
grounds the clarifying questions in real content (headings, columns, terms).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from sklearn.feature_extraction.text import TfidfVectorizer

from forgeai.ingest.loaders import Document, LoadResult


@dataclass
class DocProfile:
    doc_id: str
    file: str
    kind: str
    n_words: int
    n_pages: int | None = None
    headings: list[str] = field(default_factory=list)
    top_terms: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    n_rows: int | None = None
    sample_rows: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class CorpusProfile:
    docs: list[DocProfile]
    skipped: list[tuple[str, str]]

    @property
    def has_tables(self) -> bool:
        return any(d.kind == "table" for d in self.docs)

    @property
    def total_words(self) -> int:
        return sum(d.n_words for d in self.docs)

    def to_dict(self) -> dict:
        return {"docs": [asdict(d) for d in self.docs], "skipped": self.skipped}

    def to_prompt(self, max_chars: int = 6000) -> str:
        """Compact, LLM-readable summary. Truncated per document to fit budget."""
        lines: list[str] = [f"{len(self.docs)} document(s), ~{self.total_words} words total."]
        per_doc = max(400, max_chars // max(1, len(self.docs)))
        for d in self.docs:
            part = [f"\n## {d.doc_id} ({d.kind}, {d.n_words} words"
                    + (f", {d.n_pages} pages" if d.n_pages else "")
                    + (f", {d.n_rows} rows" if d.n_rows is not None else "") + ")"]
            if d.columns:
                part.append("Columns: " + ", ".join(d.columns))
            if d.sample_rows:
                part.append("Sample rows: " + "; ".join(str(r) for r in d.sample_rows[:2]))
            if d.headings:
                part.append("Sections: " + " | ".join(d.headings[:20]))
            if d.top_terms:
                part.append("Key terms: " + ", ".join(d.top_terms))
            if d.warnings:
                part.append("Warnings: " + "; ".join(d.warnings))
            lines.append("\n".join(part)[:per_doc])
        if self.skipped:
            lines.append("\nSkipped files: " + "; ".join(f"{f} ({r})" for f, r in self.skipped))
        return "\n".join(lines)[:max_chars]


def _top_terms(docs: list[Document], k: int = 12) -> dict[str, list[str]]:
    texts = [d.text if d.table is None else d.table.astype(str).to_string(index=False) for d in docs]
    if not any(t.strip() for t in texts):
        return {d.doc_id: [] for d in docs}
    vec = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        max_features=20000,
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z\-]{2,}\b",
        sublinear_tf=True,
    )
    try:
        m = vec.fit_transform(texts)
    except ValueError:  # empty vocabulary
        return {d.doc_id: [] for d in docs}
    vocab = vec.get_feature_names_out()
    out: dict[str, list[str]] = {}
    for i, d in enumerate(docs):
        row = m.getrow(i).toarray().ravel()
        idx = row.argsort()[::-1][:k]
        out[d.doc_id] = [vocab[j] for j in idx if row[j] > 0]
    return out


def profile_corpus(result: LoadResult) -> CorpusProfile:
    docs = result.documents
    terms = _top_terms(docs) if docs else {}
    profiles: list[DocProfile] = []
    for d in docs:
        p = DocProfile(
            doc_id=d.doc_id,
            file=d.path.name,
            kind=d.kind,
            n_words=d.n_words,
            n_pages=d.n_pages,
            top_terms=terms.get(d.doc_id, []),
            warnings=list(d.warnings),
        )
        if d.table is not None:
            p.columns = list(d.table.columns)
            p.n_rows = len(d.table)
            p.sample_rows = d.table.head(3).to_dict(orient="records")
        else:
            seen: set[str] = set()
            for b in d.blocks:
                if b.is_heading and b.text not in seen:
                    seen.add(b.text)
                    p.headings.append(b.text)
        profiles.append(p)
    return CorpusProfile(docs=profiles, skipped=list(result.skipped))
