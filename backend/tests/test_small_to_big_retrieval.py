"""Spec small-to-big-retrieval: rank small pieces, hand the extractor their parents (AC-1 to AC-32 but AC-0, AC-15, AC-16)."""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from arp.config import Settings, get_settings
from arp.extraction.field_graph import field_evidence
from arp.extraction.pipeline import input_settings
from arp.ingestion.parsing import chunk_document, small_pieces
from arp.retrieval import rerank
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import DocType, SourceDocument, TableSpan
from arp.schemas.datapoints import DocumentRouting, FieldDataType, FieldDefinition

KEY = "The group plans to reach net zero 2040 across all scopes."


def _filler(n: int, tag: str) -> str:
    """Exactly `n` chars of distinct ~80-char sentences, no field keyword, no title word."""
    t = hashlib.sha1(tag.encode()).hexdigest()[:6]
    out = "".join(f"Sentence {t} {i} says lorem ipsum dolor sit amet with plain words only here. " for i in range(n // 60 + 2))
    return out[:n]


def _sec(title: str, n: int, *inner: str, at: float | None = None) -> str:
    """`# title` section of exactly `n` chars (heading line included); `inner` sentences at its start and end,
    or a single one at fraction `at` of the body."""
    head = f"# {title}\n"
    body_n = n - len(head) - 1
    if at is not None:
        (s,) = inner
        cut = int(body_n * at)
        free = body_n - len(s) - 2
        body = _filler(cut, title + "a") + " " + s + " " + _filler(free - cut, title + "b")
    elif len(inner) == 2:
        free = body_n - len(inner[0]) - len(inner[1]) - 2
        body = inner[0] + " " + _filler(free, title) + " " + inner[1]
    elif inner:
        free = body_n - len(inner[0]) - 1
        body = _filler(free // 2, title + "a") + " " + inner[0] + _filler(free - free // 2, title + "b")
    else:
        body = _filler(body_n, title)
    assert len(head + body + "\n") == n
    return head + body + "\n"


def _doc(text: str, title: str = "Report 2024", tables=()) -> SourceDocument:
    return SourceDocument(
        doc_id="d1", company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title=title, full_text=text, table_spans=list(tables),
    )


def _field(keyword: str = "net zero", **kw) -> FieldDefinition:
    return FieldDefinition(
        field_id="f", name="F", description="d", data_type=FieldDataType.NUMBER, extraction_instructions="x",
        seed_keywords=[keyword], **kw,
    )


def _settings(**kw) -> Settings:
    return Settings(**{"hybrid_retrieval_enabled": False, "rerank_enabled": False, **kw})


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("ARP_SMALL_TO_BIG_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _off(**kw) -> Settings:
    return _settings(small_to_big_enabled=False, **kw)


def doc_t(targets: str | None = None) -> SourceDocument:
    return _doc(_sec("Intro", 2000) + (targets or _sec("Targets", 1500, KEY)) + _sec("Other", 2000))


def span(doc: SourceDocument, title: str) -> tuple[int, int]:
    start = doc.full_text.index(f"# {title}\n")
    nxt = doc.full_text.find("\n# ", start + 1)
    return start, (nxt + 1 if nxt >= 0 else len(doc.full_text))


def section_id(doc, title):
    s, e = span(doc, title)
    return f"chk_d1_{s}_{e}"


def rule2_parent(doc: SourceDocument) -> str:
    """The spec's rule-2 parent of the piece holding KEY."""
    p = next(x for x in small_pieces(doc, get_settings()) if KEY in x.text)
    plain = [c for c in chunk_document(doc) if "_table_" not in c.chunk_id]
    holding = [c for c in plain if c.char_start <= p.char_start and p.char_end <= c.char_end]
    if holding:
        return min(holding, key=lambda c: c.char_start).chunk_id
    return max(plain, key=lambda c: (min(c.char_end, p.char_end) - max(c.char_start, p.char_start), -c.char_start)).chunk_id


# --- settings -------------------------------------------------------------


def test_defaults_and_env(monkeypatch):  # AC-1, AC-17, AC-18
    monkeypatch.delenv("ARP_SMALL_TO_BIG_ENABLED", raising=False)
    assert Settings().small_to_big_enabled is False
    assert Settings().small_chunk_chars == 800
    monkeypatch.setenv("ARP_SMALL_TO_BIG_ENABLED", "true")
    assert Settings().small_to_big_enabled is True


def test_input_settings():  # AC-14, AC-21
    off = input_settings(Settings(anthropic_api_key="x"))
    assert input_settings(Settings(anthropic_api_key="x", small_to_big_enabled=True)) != off
    assert "small_to_big_enabled" not in off


# --- small pieces ---------------------------------------------------------

AB = _sec("A", 3000) + _sec("B", 3000)


def test_small_pieces():  # AC-2, AC-2b, AC-2c, AC-2d, AC-2e
    doc = _doc(AB)
    b = AB.index("# B")
    pieces = small_pieces(doc, _settings())
    assert all(len(p.text) <= 800 for p in pieces)
    assert not any(p.char_start < b < p.char_end for p in pieces)
    assert _covered(pieces) == set(range(len(AB)))
    assert all(p.chunk_id == f"chk_d1_{p.char_start}_{p.char_end}" for p in pieces)
    assert all(p.section == "B" for p in pieces if p.char_start >= b)


def _covered(pieces) -> set[int]:
    return {i for p in pieces for i in range(p.char_start, p.char_end)}


def test_pieces_cover_tables():  # AC-2f
    table = "| Year | Value |\n| 2023 | 11 |\n"
    a = _sec("A", 3000)
    text = a[:1500] + "\n" + table + a[1500:] + _sec("B", 3000)
    doc = _doc(text, tables=[TableSpan(table_id="t1", char_start=1501, char_end=1501 + len(table))])
    assert _covered(small_pieces(doc, _settings())) == set(range(len(text)))


def test_piece_size_is_in_the_cache_key():  # AC-22
    doc = _doc(AB)
    small_pieces(doc, _settings(small_chunk_chars=800))
    assert all(len(p.text) <= 400 for p in small_pieces(doc, _settings(small_chunk_chars=400)))


# --- parents --------------------------------------------------------------


def test_section_parent(on):  # AC-3, AC-11
    doc = doc_t()
    ev = field_evidence(_field(), [doc], _settings(evidence_max_chunks=1))
    assert [(c.char_start, c.char_end, c.section) for c in ev] == [(*span(doc, "Targets"), "Targets")]
    assert all(c.text == doc.full_text[c.char_start : c.char_end] for c in ev)


def test_short_section_gets_todays_chunk(on):  # AC-4
    doc = doc_t(_sec("Targets", 300, KEY))
    ev = field_evidence(_field(), [doc], _settings(evidence_max_chunks=1))
    assert [c.chunk_id for c in ev] == [rule2_parent(doc)]


def test_long_section_gets_todays_chunk(on):  # AC-5
    doc = doc_t(_sec("Targets", 8000, KEY, at=5000 / 8000))
    ev = field_evidence(_field(), [doc], _settings(evidence_max_chunks=1))
    assert [c.chunk_id for c in ev] == [rule2_parent(doc)]


def test_no_headings(on):  # AC-23
    doc = _doc(_filler(1200, "x") + " " + KEY + " " + _filler(6000, "y"))
    ev = field_evidence(_field(), [doc], _settings(evidence_max_chunks=1))
    assert [c.chunk_id for c in ev] == [chunk_document(doc)[0].chunk_id]


def test_text_before_first_heading(on):  # AC-24
    pre = _filler(1200, "x") + " " + KEY + "\n"
    doc = _doc(pre + _sec("A", 3000))
    ev = field_evidence(_field(), [doc], _settings(evidence_max_chunks=1))
    assert [(c.char_start, c.char_end, c.section) for c in ev] == [(0, len(pre), None)]


P2 = "Net zero by 2040 is the net zero aim and net zero plan."


def doc_pq() -> SourceDocument:
    return _doc(
        _sec("F1", 2000) + _sec("P", 1500, P2, "Our second net zero line is here.") + _sec("F2", 2000)
        + _sec("Q", 1500, KEY) + _sec("F3", 2000)
    )


def test_pieces_of_one_parent_count_once(on):  # AC-6
    doc = doc_pq()
    ev = field_evidence(_field(), [doc], _settings(evidence_max_chunks=2))
    assert {c.chunk_id for c in ev} == {section_id(doc, "P"), section_id(doc, "Q")}


def test_explain_is_keyed_by_parents(on):  # AC-25, AC-25b, AC-26
    doc = doc_pq()
    explain: dict = {}
    ev = field_evidence(_field(), [doc], _settings(evidence_max_chunks=1), explain=explain)
    p, q = section_id(doc, "P"), section_id(doc, "Q")
    assert [c.chunk_id for c in explain["near_miss_chunks"]] == explain["near_misses"]
    assert explain["near_misses"][0] == ({p, q} - {ev[0].chunk_id}).pop()
    assert set(explain["scores"]) == {p, q}


def test_table_passage_is_its_own_parent(on):  # AC-7
    table = "| Scope | Value |\n| One | 11 |\n"
    head = _sec("A", 1500)
    text = head + table + _sec("B", 1500)
    t = TableSpan(table_id="t1", char_start=len(head), char_end=len(head) + len(table), caption="GHG emissions")
    doc = _doc(text, tables=[t])
    ev = field_evidence(_field("emissions"), [doc], _settings())
    table_chunk = next(c for c in ev if c.chunk_id == f"chk_d1_table_{t.char_start}_{t.char_end}")
    assert table_chunk.text == text[t.char_start : t.char_end]


def test_pieces_are_indexed_with_headers(on):  # AC-8, AC-19
    doc = _doc(_sec("Plan", 1500), title="Zephyr Report 2024")
    assert [c.chunk_id for c in field_evidence(_field("zephyr"), [doc], _settings())] == [section_id(doc, "Plan")]
    assert field_evidence(_field("zephyr"), [doc], _settings(context_headers_enabled=False)) == []


# --- hybrid ---------------------------------------------------------------


class _Store:
    def __init__(self):
        self.rows = {}

    def lookup_embeddings(self, ids, model):
        return {i: self.rows[i] for i in ids if i in self.rows}

    def store_embeddings(self, vectors, model):
        self.rows.update(vectors)


def _vec(t: str) -> list[float]:
    if "\n" not in t:  # the query; every index text starts with its header line
        return [1.0, 0.0, 0.0]
    for marker, v in (("alphaq", [1.0, 0.0, 0.0]), ("betar", [0.8, 0.6, 0.0]), ("gammap", [0.6, 0.8, 0.0])):
        if marker in t:
            return v
    return [0.0, 0.0, 1.0]


@pytest.fixture
def hybrid(monkeypatch, on):
    monkeypatch.setattr("arp.retrieval.embeddings.embed_texts", lambda texts: np.array([_vec(t) for t in texts], dtype=np.float32))
    store = _Store()
    monkeypatch.setattr("arp.retrieval.content_store_factory.build_hybrid_content_store", lambda settings: store)


def doc_pqr() -> SourceDocument:
    return _doc(
        _sec("P", 1500, "Net zero now, net zero soon, net zero always gammap.", "Net zero, net zero and net zero again.")
        + _sec("Q", 1500, "We aim for net zero alphaq.") + _sec("R", 1500, "A plain betar sentence.")
    )


def test_hybrid_collapses_before_fusion(hybrid):  # AC-9, AC-27, AC-28, AC-31, AC-32
    doc = doc_pqr()
    p, q, r = (section_id(doc, x) for x in "PQR")
    explain: dict = {}
    ev = field_evidence(_field(), [doc], _settings(hybrid_retrieval_enabled=True), explain=explain)
    assert [c.chunk_id for c in ev] == [q, p, r]
    assert explain["scores"][q]["rrf"] == 1 / 61 + 1 / 62
    assert explain["small_to_big"] is True
    assert explain["scores"][p]["vector_rank"] == 3
    assert explain["scores"][r]["vector_rank"] == 2


# --- rerank, routing, fallbacks --------------------------------------------


def test_reranker_scores_parent_text(on, monkeypatch):  # AC-10
    seen: list[list[str]] = []
    monkeypatch.setattr(rerank, "_unavailable", False)
    monkeypatch.setattr(rerank.compute_client, "models_configured", lambda: False)
    monkeypatch.setattr(rerank, "_score", lambda q, texts: seen.append(list(texts)) or [1.0] * len(texts))
    doc = doc_t()
    field_evidence(_field(), [doc], _settings(rerank_enabled=True))
    s, e = span(doc, "Targets")
    assert [t for call in seen for t in call] == [doc.full_text[s:e]]


def test_section_routing(on):  # AC-29
    doc = doc_t()
    field = _field(document_routing=DocumentRouting(sections=["Targets"]))
    assert [c.chunk_id for c in field_evidence(field, [doc], _settings(evidence_max_chunks=3))] == [section_id(doc, "Targets")]


def test_high_risk_fallback_as_off(monkeypatch):  # AC-12
    doc = doc_t()
    field = _field("zzqx", high_risk=True)
    off = [c.chunk_id for c in field_evidence(field, [doc], _off())]
    monkeypatch.setenv("ARP_SMALL_TO_BIG_ENABLED", "true")
    assert off and [c.chunk_id for c in field_evidence(field, [doc], _settings(small_to_big_enabled=True))] == off


class _FakeOpenSearch:
    def search(self, index, body):
        ids = body["query"]["bool"]["filter"]["terms"]["chunk_id"]
        return {"hits": {"hits": [{"_source": {"chunk_id": cid}, "_score": float(20 - i)} for i, cid in enumerate(ids[:10])]}}


def test_opensearch_unchanged(monkeypatch):  # AC-13
    monkeypatch.setattr("arp.storage.opensearch_client.get_client", lambda url: _FakeOpenSearch())
    doc = doc_t()
    kw = {"retrieval_backend": "opensearch", "opensearch_url": "http://x"}
    off = [c.chunk_id for c in field_evidence(_field(), [doc], _off(**kw))]
    on = [c.chunk_id for c in field_evidence(_field(), [doc], _settings(small_to_big_enabled=True, **kw))]
    assert off and on == off


def test_other_callers_unchanged(monkeypatch):  # AC-30
    doc = doc_t()

    def ids():
        get_settings.cache_clear()
        return [c.chunk_id for c in select_relevant_chunks(chunk_document(doc, keywords=["net zero"]), ["net zero"], max_chunks=3)]

    off = ids()
    monkeypatch.setenv("ARP_SMALL_TO_BIG_ENABLED", "true")
    assert ids() == off
    get_settings.cache_clear()
