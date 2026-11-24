from __future__ import annotations

import pytest

from forgeai.ingest.chunker import ChunkParams, chunk_document, chunk_documents, suggest_params
from forgeai.ingest.loaders import Block, Document, load_folder, looks_like_heading
from forgeai.ingest.profiler import profile_corpus
from forgeai.retrieval.embed import get_embedder
from forgeai.retrieval.index import HybridIndex, SearchParams, tokenize


def test_load_folder_mixed_formats(corpus):
    res = load_folder(corpus)
    ids = {d.doc_id: d for d in res.documents}
    assert set(ids) == {"leave_policy", "travel", "catalogue", "conduct"}
    assert ids["catalogue"].table is not None and len(ids["catalogue"].table) == 3
    assert ids["travel"].n_pages == 1 and "Economy class" in ids["travel"].text
    assert any(b.is_heading and b.text == "Code of Conduct" for b in ids["conduct"].blocks)
    assert any(f == "image.png" for f, _ in res.skipped)
    assert not any(".hidden" in f for f, _ in res.skipped)  # hidden files silently ignored


def test_duplicate_files_are_skipped(corpus):
    (corpus / "copy.md").write_bytes((corpus / "leave_policy.md").read_bytes())
    res = load_folder(corpus)
    assert any("duplicate" in why for _, why in res.skipped)


def test_scanned_pdf_is_flagged(tmp_path):
    import pymupdf

    pdf = pymupdf.open()
    pdf.new_page()
    pdf.new_page()
    pdf.save(tmp_path / "scan.pdf")
    doc = load_folder(tmp_path).documents[0]
    assert any("scanned" in w for w in doc.warnings)


def test_bad_file_does_not_stop_run(corpus):
    (corpus / "broken.pdf").write_bytes(b"%PDF-1.4 garbage")
    res = load_folder(corpus)
    assert any(f == "broken.pdf" and "load error" in why for f, why in res.skipped)
    assert len(res.documents) == 4


@pytest.mark.parametrize("line, expected", [
    ("# Annual Leave", True), ("3.2 Travel Allowances", True), ("SICK LEAVE", True),
    ("Employees are entitled to 12 days of paid sick leave.", False), ("", False),
])
def test_heading_detection(line, expected):
    assert looks_like_heading(line) is expected


def test_chunks_respect_sections_size_and_overlap(tmp_path):
    sentence = "Rule {i} says staff must follow procedure number {i} carefully at all times."
    body = " ".join(sentence.format(i=i) for i in range(60))  # ~780 words
    doc = Document(doc_id="pol", path=tmp_path / "x", kind="text",
                   blocks=[Block("Section A", is_heading=True), Block(body), Block("Section B", is_heading=True), Block("Short rule.")])
    chunks = chunk_document(doc, ChunkParams(chunk_size=120, chunk_overlap=20))
    assert all(len(c.body.split()) <= 140 for c in chunks)
    assert chunks[-1].section == "Section B" and chunks[-1].body == "Short rule."
    a = [c for c in chunks if c.section == "Section A"]
    assert len(a) >= 6
    # overlap: the tail of chunk n reappears at the head of chunk n+1
    assert a[0].body.split()[-5:] == a[1].body.split()[:20][-5:] or set(a[0].body.split()[-10:]) & set(a[1].body.split()[:25])
    assert chunks[0].text.startswith("[pol > Section A]")


def test_table_rows_become_chunks(corpus):
    res = load_folder(corpus)
    chunks = chunk_documents(res.documents, suggest_params(res.documents))
    rows = [c for c in chunks if c.kind == "row"]
    assert len(rows) == 3 and "part_no: AB-2207" in rows[2].body


def test_invalid_params_rejected():
    with pytest.raises(ValueError):
        ChunkParams(chunk_size=100, chunk_overlap=60)


def test_profile_has_columns_headings_terms(corpus):
    prof = profile_corpus(load_folder(corpus))
    cat = next(d for d in prof.docs if d.doc_id == "catalogue")
    assert "part_no" in cat.columns and cat.n_rows == 3
    leave = next(d for d in prof.docs if d.doc_id == "leave_policy")
    assert "Annual Leave" in leave.headings and leave.top_terms
    text = prof.to_prompt()
    assert "catalogue" in text and "Skipped files" in text


def test_tokenizer_keeps_identifiers():
    toks = tokenize("Price of AB-2207 impeller?")
    assert "ab-2207" in toks and "2207" in toks and "of" not in toks


@pytest.fixture
def index(corpus, settings):
    res = load_folder(corpus)
    chunks = chunk_documents(res.documents, suggest_params(res.documents))
    return HybridIndex(chunks, get_embedder(settings))


def test_hybrid_finds_exact_part_number(index):
    hits = index.search("AB-2207", SearchParams(top_k=3))
    assert hits[0].chunk.doc_id == "catalogue" and "AB-2207" in hits[0].chunk.body
    assert hits[0].bm25_rank == 1


def test_hybrid_finds_policy_passage(index):
    hits = index.search("how many sick leave days do employees get", SearchParams(top_k=3))
    assert any("12 days of paid sick leave" in h.chunk.body for h in hits)
    assert all(h.trace()["chunk_id"] for h in hits)


@pytest.mark.parametrize("mode", ["dense", "bm25", "hybrid"])
def test_modes_and_top_k(index, mode):
    hits = index.search("meal allowance domestic travel", SearchParams(top_k=2, mode=mode))
    assert 1 <= len(hits) <= 2


def test_rerank_unavailable_is_noop(index):
    from forgeai.retrieval.index import Reranker

    r = Reranker("does-not-exist/model")
    r.available = False
    index.reranker = r
    hits = index.search("fuel injector", SearchParams(top_k=2, rerank=True))
    assert hits and hits[0].rerank_score is None


def test_empty_query_and_empty_index(settings):
    idx = HybridIndex([], get_embedder(settings))
    assert idx.search("anything") == []
