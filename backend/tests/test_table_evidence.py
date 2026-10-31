from arp.config import Settings
from arp.extraction import field_graph
from arp.extraction.extractor_agent import format_evidence
from arp.extraction.field_graph import field_evidence, swap_tables
from arp.grounding import ground_citations
from arp.ingestion.parsing import chunk_document
from arp.schemas.common import Citation, DocType, DocumentChunk, SourceDocument, TableSpan
from arp.schemas.datapoints import FieldDataType, FieldDefinition


def _chunk(i: int, start: int, end: int, **kw) -> DocumentChunk:
    return DocumentChunk(chunk_id=f"c{i}", doc_id="d1", company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT,
                         text="x" * (end - start), char_start=start, char_end=end, **kw)


def _table(start: int, end: int) -> DocumentChunk:
    return _chunk(99, start, end, table_id="table_0")


def _field_evidence(monkeypatch, ranked, all_chunks, settings=None):
    monkeypatch.setattr(field_graph, "route_documents", lambda field, docs: docs)
    monkeypatch.setattr(field_graph, "chunk_document", lambda doc, keywords: all_chunks)
    monkeypatch.setattr(field_graph, "select_relevant_chunks", lambda *a, **kw: ranked)
    field = FieldDefinition(field_id="capex_total", name="CapEx", description="d", extraction_instructions="d",
                            data_type=FieldDataType.CURRENCY_AMOUNT)
    return field_evidence(field, [object()], settings)


def test_ac10_overlapping_text_passage_is_swapped_for_the_whole_table(monkeypatch):
    text, other, table = _chunk(1, 0, 3500), _chunk(2, 12_000, 13_000), _table(2000, 10_000)
    out = _field_evidence(monkeypatch, [text, other], [text, other, table])
    assert [c.chunk_id for c in out] == ["c99", "c2"]


def test_ac11_table_over_the_cap_is_not_swapped_in(monkeypatch):
    text, table = _chunk(1, 0, 3500), _table(2000, 22_000)
    out = _field_evidence(monkeypatch, [text], [text, table], Settings(evidence_table_max_chars=12_000))
    assert [c.chunk_id for c in out] == ["c1"]


def test_ac12_two_passages_in_one_table_give_it_once():
    a, b, table = _chunk(1, 0, 3500), _chunk(2, 3200, 6700), _table(1000, 6000)
    assert [c.chunk_id for c in swap_tables([a, b], [a, b, table], 12_000)] == ["c99"]


def test_ac13_swap_never_refills():
    # 12 selected; ranks 2, 5 and 9 (1-based) overlap one table
    selected = [_chunk(i, i * 10_000, i * 10_000 + 100) for i in range(12)]
    for rank in (1, 4, 8):
        selected[rank] = _chunk(rank, 500_000 + rank, 500_000 + rank + 100)
    table = _table(500_000, 501_000)
    out = swap_tables(selected, [*selected, table], 12_000)
    assert len(out) == 10
    assert out[1].chunk_id == "c99"
    assert [c.chunk_id for c in out if c.chunk_id != "c99"] == [f"c{i}" for i in range(12) if i not in (1, 4, 8)]


def test_ac14_table_passage_header_line():
    span = TableSpan(table_id="table_0", char_start=0, char_end=5, page=102, kind="eu_taxonomy_capex", caption="CapEx KPI",
                     unit="€", scale="million", column_headers=["A", "B"])
    chunk = _chunk(1, 0, 5, table_id="table_0", table=span, caption="CapEx KPI", page=102)
    header = format_evidence([chunk]).split("\n")[0]
    for part in ("page=102", "table=eu_taxonomy_capex", 'caption="CapEx KPI"', "unit=€", "scale=million", "columns=A | B"):
        assert part in header


def test_ac23b_grounding_is_the_same_against_text_and_table_passage():
    md = "| | 2025 |\n|---|---|\n| Wind | 1,234 |"
    text = f"## EU Taxonomy\n\nIntro.\n\n{md}\n\nAfter."
    start = text.index(md)
    doc = SourceDocument(doc_id="d1", company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t", full_text=text,
                         table_spans=[TableSpan(table_id="table_0", char_start=start, char_end=start + len(md))])
    chunks = chunk_document(doc)
    table = next(c for c in chunks if c.table_id)
    passage = next(c for c in chunks if not c.table_id)
    results = []
    for p in (passage, table):
        (c,) = ground_citations([Citation(doc_id="d1", doc_type=doc.doc_type, quote="Wind | 1,234", passage_id=p.chunk_id)],
                                {"d1": doc}, passages={p.chunk_id: p})
        results.append((c.grounded, c.char_start, c.char_end))
    assert results[0] == results[1] and results[0][0]
