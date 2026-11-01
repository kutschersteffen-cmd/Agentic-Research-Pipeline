"""Spec section-chunks-context-headers-document-tree: outline, section-bounded chunking, index text, doc tree."""

from __future__ import annotations

import hashlib
import json

import pytest
from typer.testing import CliRunner

from arp.config import Settings, get_settings
from arp.ingestion.chunk_spans import get_span_cache
from arp.ingestion.outline import heading_path, outline
from arp.ingestion.parsing import chunk_document
from arp.retrieval.index_text import index_text
from arp.schemas.common import DocType, SourceDocument, TableCell, TableSpan


def _doc(parts: list[str], page_breaks=(), tables=(), **kw) -> SourceDocument:
    return SourceDocument(
        doc_id="d1", company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title=kw.pop("title", "R"),
        full_text="".join(parts), page_breaks=list(page_breaks), table_spans=list(tables), **kw,
    )


def _section(heading: str, body_chars: int) -> str:
    line = heading + "\n"
    # distinct sentences: the splitter locates repeated text at its first occurrence
    tag = hashlib.sha1(heading.encode()).hexdigest()[:8]
    body = "".join(f"Sentence {tag} {i} says ipsum. " for i in range(body_chars // 20 + 1))[: max(0, body_chars - len(line) - 1)]
    return line + body + "\n"


@pytest.fixture
def sections_on(monkeypatch):
    monkeypatch.setenv("ARP_SECTION_CHUNKING_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _spans(doc):
    return [(c.char_start, c.char_end, c.section) for c in chunk_document(doc) if c.table_id is None]


# --- Part 0 ---------------------------------------------------------------


def test_outline_skips_table_headings_and_reads_pages():
    a, a1 = "# A\nintro\n", "## A1\nbody\n"
    table = "## X\n| 1 | 2 |\n"
    b = "# B\nend\n"
    text = a + a1 + table + b
    t0 = len(a + a1)
    doc = _doc([text], page_breaks=[len(a), t0 + len(table)], tables=[TableSpan(table_id="t1", char_start=t0, char_end=t0 + len(table))])
    assert [(e.title, e.level, e.page) for e in outline(doc)] == [("A", 1, 1), ("A1", 2, 2), ("B", 1, 3)]
    assert heading_path(doc, len(a) + 3) == ["A", "A1"]
    assert heading_path(doc, len(text) - 2) == ["B"]


# --- Part A ---------------------------------------------------------------


def test_sections_never_cross_a_heading(sections_on):
    a, b = _section("## A", 2000), _section("## B", 2000)
    spans = _spans(_doc([a, b]))
    assert all(not (s < len(a) < e) for s, e, _ in spans)
    assert all(sec == ("A" if s < len(a) else "B") for s, _, sec in spans)


def test_long_section_splits_inside_its_bounds(sections_on):
    a, b = _section("## A", 9000), _section("## B", 500)
    in_a = [(s, e) for s, e, _ in _spans(_doc([a, b])) if s < len(a)]
    assert len(in_a) >= 3 and all(e - s <= 3500 and e <= len(a) for s, e in in_a)


@pytest.mark.parametrize(
    "parts, expect_end",
    [
        ([("## A", 200), ("## B", 300), ("# C", 2000)], 2),  # stops before the shallower # C
        ([("## A", 200), ("### A.1", 700), ("## B", 2000)], 2),  # joins the deeper heading, then reaches 800
        ([("## A", 200), ("## B", 2000)], 2),  # A+B fits one chunk
        ([("## A", 200), ("# Z", 2000)], 1),
    ],
)
def test_short_sections_join_forward(sections_on, parts, expect_end):
    texts = [_section(h, n) for h, n in parts]
    doc = _doc(texts)
    end = len("".join(texts[:expect_end]))
    assert (0, end, "A") in _spans(doc)


def test_settings_off_and_few_headings_chunk_as_before(monkeypatch):
    doc = _doc([_section("## A", 5000), _section("## B", 4000)])
    off = _spans(doc)
    one_heading = _doc([_section("## A", 9000)])
    one_off = _spans(one_heading)
    monkeypatch.setenv("ARP_SECTION_CHUNKING_ENABLED", "true")
    get_settings.cache_clear()
    try:
        assert _spans(doc) != off  # the setting is read, and the span cache does not hand back the old spans
        assert _spans(one_heading) == one_off
        get_span_cache().clear()
        on = _spans(doc)
    finally:
        monkeypatch.delenv("ARP_SECTION_CHUNKING_ENABLED")
        get_settings.cache_clear()
    assert _spans(doc) == off
    covered = set()
    for s, e, _ in on:
        covered.update(range(s, e))
    assert covered == set(range(len(doc.full_text)))


# --- Part B ---------------------------------------------------------------


def _headers(on: bool) -> Settings:
    return Settings(context_headers_enabled=on)


def test_index_text_header_line():
    sus, scope = "# Sustainability\nx\n", "## Scope 3\nWe cut it by 12%.\n"
    doc = _doc([sus, scope], title="Siemens Annual Report 2025", fiscal_period="FY2025")
    chunk = next(c for c in chunk_document(doc) if c.char_start == 0)
    chunk = chunk.model_copy(update={"char_start": len(sus)})
    assert index_text(chunk, doc, _headers(True)) == "Siemens Annual Report 2025 · FY2025 · Sustainability › Scope 3\n" + chunk.text
    assert index_text(chunk, doc.model_copy(update={"fiscal_period": None}), _headers(True)).startswith(
        "Siemens Annual Report 2025 · Sustainability › Scope 3\n"
    )
    assert index_text(chunk, doc, _headers(False)) == chunk.text


def test_index_text_table_line():
    head, table = "## Emissions\n", "| 1 | 2 | 3 |\n"
    cells = [TableCell(col_label=c, char_start=0, char_end=1) for c in ("Scope 1", "Scope 2", "Scope 1", None)]
    span = TableSpan(table_id="t1", char_start=len(head), char_end=len(head + table), caption="GHG emissions", unit_note="tCO2e", cells=cells)
    doc = _doc([head, table], tables=[span])
    chunk = next(c for c in chunk_document(doc) if c.table_id == "t1")
    assert index_text(chunk, doc, _headers(True)) == "R · Emissions\nTable: GHG emissions · tCO2e · Scope 1 | Scope 2\n" + chunk.text
    bare = doc.model_copy(update={"table_spans": [span.model_copy(update={"caption": None, "unit_note": None})]})
    assert index_text(chunk, bare, _headers(True)).split("\n")[1] == "Table: Scope 1 | Scope 2"


def test_headers_rank_by_heading_but_evidence_keeps_chunk_text():
    from arp.extraction.field_graph import field_evidence
    from arp.schemas.datapoints import FieldDataType, FieldDefinition

    parts = [_section(f"## Topic {i}", 1200) for i in range(4)] + [_section("## Scope 3", 1200)]
    doc = _doc(parts)
    field = FieldDefinition(
        field_id="f", name="Scope 3", description="d", data_type=FieldDataType.NUMBER,
        extraction_instructions="x", seed_keywords=["Scope 3"],
    )
    off = field_evidence(field, [doc], Settings(hybrid_retrieval_enabled=False, rerank_enabled=False))
    on = field_evidence(field, [doc], Settings(hybrid_retrieval_enabled=False, rerank_enabled=False, context_headers_enabled=True))
    assert heading_path(doc, on[0].char_start) == ["Scope 3"]  # ranked by the header, whatever its text says
    assert all(c.text == doc.full_text[c.char_start : c.char_end] for c in on)
    assert {c.chunk_id for c in off} <= {c.chunk_id for c in chunk_document(doc)}


def test_embedding_cache_separates_index_text(monkeypatch):
    import numpy as np

    from arp.retrieval import embeddings
    from arp.retrieval.select_evidence import select_relevant_chunks

    class _Store:
        def __init__(self):
            self.rows = {}

        def lookup_embeddings(self, ids, model):
            return {i: self.rows[i] for i in ids if i in self.rows}

        def store_embeddings(self, vectors, model):
            self.rows.update(vectors)

    embedded: list[str] = []
    monkeypatch.setattr(embeddings, "embed_texts", lambda texts: embedded.extend(texts) or np.ones((len(texts), 3), dtype=np.float32))
    doc = _doc([_section("## A", 1200), _section("## B", 1200)])
    chunks = chunk_document(doc)
    store = _Store()
    select_relevant_chunks(chunks, ["ipsum"], hybrid_retrieval_enabled=True, content_store=store)
    texts = {c.chunk_id: index_text(c, doc, _headers(True)) for c in chunks}
    embedded.clear()
    for _ in range(2):
        select_relevant_chunks(chunks, ["ipsum"], hybrid_retrieval_enabled=True, content_store=store, index_texts=texts)
    assert sorted(t for t in embedded if t != "ipsum") == sorted(texts.values())  # once each, never the plain text


# --- Part C ---------------------------------------------------------------


def _tree_doc():
    a, a1_head, table, a1_tail, a2, b1, b2 = "# A\nintro\n", "## A1\n", "| 1 | 2 |\n", "more\n", "## A2\ntext\n", "# B\np4\n", "page five\n"
    text = a + a1_head + table + a1_tail + a2 + b1 + b2
    t0 = len(a + a1_head)
    p2, p3 = len(a), len(a + a1_head + table + a1_tail)
    p4, p5 = p3 + len(a2), p3 + len(a2) + len(b1)
    span = TableSpan(table_id="t1", char_start=t0, char_end=t0 + len(table), caption="GHG")
    return _doc([text], page_breaks=[p2, p3, p4, p5], tables=[span])


@pytest.fixture
def standins(tmp_path, monkeypatch):
    folder = tmp_path / "standins"
    (folder / "model").mkdir(parents=True)
    monkeypatch.setenv("ARP_STANDINS_DIR", str(folder))
    monkeypatch.delenv("ARP_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ARP_GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ARP_DOCUMENT_STORE_DIR", str(tmp_path / "store"))
    get_settings.cache_clear()
    yield folder
    get_settings.cache_clear()


def _answer(folder, ids):
    nodes = [{"node_id": i, "summary": f"about {i}", "key_terms": [i, "t"]} for i in ids]
    (folder / "model" / "TreeSummaries.json").write_text(json.dumps({"output": {"nodes": nodes}}))


def _calls(folder):
    path = folder / "calls.jsonl"
    lines = path.read_text().splitlines() if path.exists() else []
    return [json.loads(line) for line in lines if json.loads(line).get("name") == "TreeSummaries"]


def test_doc_tree_structure_summaries_and_cache(standins, monkeypatch):
    from arp.ingestion import doc_tree

    doc = _tree_doc()
    _answer(standins, [f"{i:04d}" for i in range(10)])
    tree = doc_tree.build_doc_tree(doc, get_settings())
    a, b = tree.root.children
    assert [n.title for n in tree.root.children] == ["A", "B"]
    assert [n.title for n in a.children] == ["A1", "A2"]
    assert [c.table_id for c in a.children[0].children] == ["t1"]
    assert (a.page_start, a.page_end, a.children[0].page_start, a.children[0].page_end, b.page_start, b.page_end) == (1, 3, 2, 2, 4, 5)
    assert a.summary == f"about {a.node_id}" and not tree.incomplete
    first = len(_calls(standins))
    assert first == 3  # leaves, then A1 (holds the table), then A
    doc_tree.build_doc_tree(doc, get_settings())
    assert len(_calls(standins)) == first
    monkeypatch.setattr(doc_tree, "TREE_VERSION", 2)
    assert doc_tree.build_doc_tree(doc, get_settings()).tree_version == 2
    assert len(_calls(standins)) > first


def test_doc_tree_retries_missing_nodes_and_cli(standins):
    from arp.cli.documents import documents_app as app
    from arp.ingestion import doc_tree

    doc = _tree_doc()
    _answer(standins, ["0000", "0001", "0002", "0004"])  # no A2 (0003)
    tree = doc_tree.build_doc_tree(doc, get_settings())
    a2 = tree.root.children[0].children[1]
    assert (a2.node_id, a2.summary, a2.key_terms, tree.incomplete) == ("0003", None, [], True)
    _answer(standins, ["0003"])
    before = len(_calls(standins))
    tree = doc_tree.build_doc_tree(doc, get_settings())
    retry = _calls(standins)[before:]
    assert len(retry) == 1 and "0003" in retry[0]["prompt"] and "0002" not in retry[0]["prompt"]
    assert not tree.incomplete

    result = CliRunner().invoke(app, ["tree", "d1"])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[:2] == ["A (p.1–3) [2 terms]", "  A1 (p.2–2) [2 terms]"]
    missing = CliRunner().invoke(app, ["tree", "nope"])
    assert missing.exit_code == 1 and "No tree stored for nope." in missing.output


def test_doc_tree_page_windows_and_batches(standins):
    from arp.ingestion import doc_tree

    few = _doc(["# A\n" + "x\n" * 60 + "# B\n" + "y\n" * 60], page_breaks=[i * 20 for i in range(1, 12)])
    _answer(standins, [f"{i:04d}" for i in range(3)])
    assert [n.title for n in doc_tree.build_doc_tree(few, get_settings()).root.children] == ["Pages 1–5", "Pages 6–10", "Pages 11–12"]

    many = _doc(["# Top\n"] + [f"## S{i}\nbody {i}\n" for i in range(45)])
    _answer(standins, [f"{i:04d}" for i in range(46)])
    before = len(_calls(standins))
    doc_tree.build_doc_tree(many, get_settings())
    sizes = [sum(f"node_id: {i:04d}\n" in c["prompt"] for i in range(46)) for c in _calls(standins)[before:]]
    assert sizes == [20, 20, 5, 1]
