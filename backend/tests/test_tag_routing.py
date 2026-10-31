from arp.extraction import field_graph
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.field_graph import extract_one_field, field_evidence
from arp.extraction.verifier_agent import VerifierOutput
from arp.planning.doc_routing import section_filter
from arp.schemas.common import Citation, DocType, DocumentChunk, SourceDocument, TableSpan
from arp.schemas.datapoints import DocumentRouting, FieldDataType, FieldDefinition

_TEXT = "Our capex was EUR 100 million in 2024. " * 40
_DOC = SourceDocument(doc_id="d1", company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="t", full_text=_TEXT)
_ROUTING = DocumentRouting(table_kinds=["eu_taxonomy_capex"], section_tags=["eu_taxonomy"])


def _field(routing=_ROUTING) -> FieldDefinition:
    return FieldDefinition(field_id="capex_total", name="capex", description="d", data_type=FieldDataType.NUMBER,
                           extraction_instructions="look", seed_keywords=["capex"], document_routing=routing)


def _chunk(i, **kw) -> DocumentChunk:
    start = i * 100
    return DocumentChunk(chunk_id=f"c{i}", doc_id="d1", company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT,
                         text=_TEXT[start : start + 80], char_start=start, char_end=start + 80, keyword_hits=["capex"], **kw)


def _six():
    table = _chunk(0, table_id="table_0", table=TableSpan(table_id="table_0", char_start=0, char_end=80, kind="eu_taxonomy_capex"))
    return [table, _chunk(1, section_tags=["eu_taxonomy"]), _chunk(2, section_tags=["eu_taxonomy"]),
            _chunk(3), _chunk(4, section_tags=["governance"]), _chunk(5)]


def _patch_chunks(monkeypatch, chunks):
    monkeypatch.setattr(field_graph, "chunk_document", lambda doc, keywords: chunks)


def test_ac15_routed_evidence_stays_in_the_table_and_tagged_sections(monkeypatch):
    _patch_chunks(monkeypatch, _six())
    out = field_evidence(_field(), [_DOC], None)
    assert out and {c.chunk_id for c in out} <= {"c0", "c1", "c2"}


def test_ac16_no_match_gives_the_unrouted_evidence():
    routed = field_evidence(_field(), [_DOC], None)
    plain = field_evidence(_field(routing=None), [_DOC], None)
    assert routed and [c.chunk_id for c in routed] == [c.chunk_id for c in plain]


def _llm(fake_llm):
    draft = ExtractionDraft(values=[PeriodValue(value=100, raw_value_text="EUR 100 million", citations=[
        Citation(doc_id="d1", doc_type=_DOC.doc_type, quote="EUR 100 million")])], confidence=0.9)
    return fake_llm({"ExtractionDraft": [draft], "VerifierOutput": [VerifierOutput(agrees=True, confidence=0.9, notes="ok")]})


async def _trace(fake_llm):
    sink = {}
    llm = _llm(fake_llm)
    await extract_one_field("Acme", _field(), documents=[_DOC], documents_by_id={"d1": _DOC}, llm=llm, verifier_llm=llm,
                            fuzzy_threshold=0.9, confidence_review_threshold=0.6, trace_sink=sink)
    return sink["capex_total"]["routing"]


async def test_ac17_trace_records_the_routing(fake_llm, monkeypatch):
    _patch_chunks(monkeypatch, _six())
    assert await _trace(fake_llm) == {"matched": True, "tags": ["eu_taxonomy"], "table_kinds": ["eu_taxonomy_capex"],
                                      "kept": 3, "of": 6}


async def test_ac18_trace_records_no_match(fake_llm):
    assert (await _trace(fake_llm))["matched"] is False


def test_old_sections_and_new_tags_keep_a_chunk_matching_either():
    by_heading = _chunk(1, section="Climate strategy")
    by_tag = _chunk(2, section_tags=["eu_taxonomy"])
    neither = _chunk(3, section="Other")
    field = _field(DocumentRouting(sections=["climate"], section_tags=["eu_taxonomy"]))
    assert section_filter(field, [by_heading, by_tag, neither]) == [by_heading, by_tag]
