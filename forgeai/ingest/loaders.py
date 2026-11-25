"""Load an arbitrary document folder into a uniform ``Document`` model.

The review uses a folder we have never seen, so the rules are:
* never crash on a bad file - skip it and record why;
* surface silent failures (e.g. scanned PDFs with no text layer) as warnings
  that flow into the groundability guard and the final report;
* keep tabular files as real tables (for the CSV lookup tool) *and* as text
  rows (for retrieval).
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

TEXT_EXT = {".txt", ".md", ".markdown", ".rst", ".json", ".yaml", ".yml"}
HTML_EXT = {".html", ".htm"}
TABLE_EXT = {".csv", ".tsv", ".xlsx", ".xls"}
SUPPORTED = TEXT_EXT | HTML_EXT | TABLE_EXT | {".pdf", ".docx"}
MAX_FILE_MB = 50
MAX_TABLE_ROWS = 50_000


@dataclass
class Block:
    """A paragraph-level unit of text with its location."""

    text: str
    page: int | None = None
    is_heading: bool = False


@dataclass
class Document:
    doc_id: str
    path: Path
    kind: str
    blocks: list[Block] = field(default_factory=list)
    table: pd.DataFrame | None = None
    n_pages: int | None = None
    content_hash: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)

    @property
    def n_words(self) -> int:
        if self.table is not None:
            return int(self.table.astype(str).map(lambda v: len(v.split())).to_numpy().sum())
        return sum(len(b.text.split()) for b in self.blocks)


@dataclass
class LoadResult:
    documents: list[Document]
    skipped: list[tuple[str, str]]

    @property
    def tables(self) -> dict[str, pd.DataFrame]:
        return {d.doc_id: d.table for d in self.documents if d.table is not None}


_SLUG = re.compile(r"[^a-z0-9]+")
_NUMBERED_HEADING = re.compile(r"^(\d+(\.\d+){0,3}\.?|[IVX]+\.|[A-Z]\.)\s+[A-Z][^.!?]{2,80}$")


def slugify(name: str) -> str:
    return _SLUG.sub("_", name.lower()).strip("_") or "doc"


def looks_like_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 90 or s.endswith((".", ",", ";")):
        return False
    if s.startswith("#"):
        return True
    if _NUMBERED_HEADING.match(s):
        return True
    words = s.split()
    letters = [c for c in s if c.isalpha()]
    if 1 <= len(words) <= 10 and letters and sum(c.isupper() for c in letters) / len(letters) > 0.8:
        return True
    return False


def _paragraphs(text: str, page: int | None = None) -> list[Block]:
    import unicodedata

    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    blocks: list[Block] = []
    for para in re.split(r"\n\s*\n", text):
        buf: list[str] = []

        def flush() -> None:
            if buf:
                blocks.append(Block(re.sub(r"\s+", " ", " ".join(buf)), page))
                buf.clear()

        for ln in (x.strip() for x in para.split("\n")):
            if not ln:
                continue
            if looks_like_heading(ln):
                flush()
                blocks.append(Block(ln.lstrip("# ").strip(), page, is_heading=True))
            else:
                buf.append(ln)
        flush()
    return blocks


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _load_pdf(path: Path, doc: Document) -> None:
    import pymupdf

    with pymupdf.open(path) as pdf:
        doc.n_pages = pdf.page_count
        empty_pages = 0
        for i, page in enumerate(pdf, start=1):
            text = page.get_text("text") or ""
            if len(text.strip()) < 20:
                empty_pages += 1
            doc.blocks.extend(_paragraphs(text, page=i))
    if doc.n_pages and empty_pages / doc.n_pages > 0.5:
        doc.warnings.append(
            f"{empty_pages}/{doc.n_pages} pages have no text layer (likely scanned); "
            "content on those pages is invisible to the agent (no OCR)."
        )


def _load_docx(path: Path, doc: Document) -> None:
    import docx

    d = docx.Document(str(path))
    for p in d.paragraphs:
        t = p.text.strip()
        if not t:
            continue
        style = (p.style.name or "").lower() if p.style is not None else ""
        doc.blocks.append(Block(t, is_heading=style.startswith(("heading", "title"))))
    for ti, table in enumerate(d.tables, start=1):
        rows = [" | ".join(c.text.strip() for c in r.cells) for r in table.rows]
        if rows:
            doc.blocks.append(Block(f"Table {ti}:\n" + "\n".join(rows)))


def _load_html(path: Path, doc: Document) -> None:
    html = _read_text(path)
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</li>|</tr>", "\n\n", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    doc.blocks.extend(_paragraphs(text))


def _load_table(path: Path, doc: Document) -> None:
    ext = path.suffix.lower()
    if ext in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    else:
        text = _read_text(path)
        sep = "\t" if ext == ".tsv" else None
        if sep is None:
            try:
                sep = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
            except csv.Error:
                sep = ","
        df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all")
    if len(df) > MAX_TABLE_ROWS:
        doc.warnings.append(f"table truncated to {MAX_TABLE_ROWS} of {len(df)} rows")
        df = df.head(MAX_TABLE_ROWS)
    doc.table = df.reset_index(drop=True)


def load_file(path: Path, root: Path | None = None) -> Document:
    rel = path.relative_to(root) if root else Path(path.name)
    ext = path.suffix.lower()
    kind = (
        "pdf"
        if ext == ".pdf"
        else "docx"
        if ext == ".docx"
        else "table"
        if ext in TABLE_EXT
        else "html"
        if ext in HTML_EXT
        else "text"
    )
    doc = Document(doc_id=slugify(str(rel.with_suffix(""))), path=path, kind=kind)
    doc.content_hash = _hash_file(path)
    if kind == "pdf":
        _load_pdf(path, doc)
    elif kind == "docx":
        _load_docx(path, doc)
    elif kind == "table":
        _load_table(path, doc)
    elif kind == "html":
        _load_html(path, doc)
    else:
        doc.blocks.extend(_paragraphs(_read_text(path)))
    if doc.table is None and not any(b.text.strip() for b in doc.blocks):
        doc.warnings.append("no extractable text")
    return doc


def load_folder(folder: str | Path) -> LoadResult:
    root = Path(folder).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"document folder not found: {root}")
    paths = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
    base = root.parent if root.is_file() else root

    docs: list[Document] = []
    skipped: list[tuple[str, str]] = []
    seen_hashes: dict[str, str] = {}
    used_ids: set[str] = set()

    for p in paths:
        rel = str(p.relative_to(base))
        if any(part.startswith(".") for part in p.relative_to(base).parts):
            continue
        if p.suffix.lower() not in SUPPORTED:
            skipped.append((rel, f"unsupported type '{p.suffix or 'none'}'"))
            continue
        if p.stat().st_size > MAX_FILE_MB * 1024 * 1024:
            skipped.append((rel, f"larger than {MAX_FILE_MB} MB"))
            continue
        try:
            doc = load_file(p, base)
        except Exception as exc:
            log.warning("failed to load %s: %s", rel, exc)
            skipped.append((rel, f"load error: {type(exc).__name__}: {exc}"[:200]))
            continue
        if doc.content_hash in seen_hashes:
            skipped.append((rel, f"duplicate of {seen_hashes[doc.content_hash]}"))
            continue
        seen_hashes[doc.content_hash] = rel
        base_id, n = doc.doc_id, 2
        while doc.doc_id in used_ids:
            doc.doc_id = f"{base_id}_{n}"
            n += 1
        used_ids.add(doc.doc_id)
        docs.append(doc)

    return LoadResult(documents=docs, skipped=skipped)
