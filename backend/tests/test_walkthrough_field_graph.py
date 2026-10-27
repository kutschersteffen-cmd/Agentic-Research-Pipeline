"""The field graph's walkthrough trace: built from what the graph already holds, only when a sink is passed."""

import pytest
from reportlab.pdfgen import canvas

from arp.config import Settings
from arp.extraction.adjudicator import AdjudicatorOutput
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.field_graph import extract_one_field
from arp.extraction.verifier_agent import VerifierOutput
from arp.extraction.vision_check import PageReading
from arp.ingestion.parsing import chunk_document
from arp.ingestion.xbrl import CompanyFactsSource
from arp.schemas.common import Citation, DocType, SourceDocument
from arp.schemas.datapoints import FieldDataType, FieldDefinition

_TEXT = "Acme annual report. Scope 1 emissions were 120 tonnes in 2024. Intensity was 2.8 per unit."
_DOC = SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG", full_text=_TEXT)
_KEYS = {"doc_id", "char_start", "char_end", "section"}


def _field(**kw) -> FieldDefinition:
    return FieldDefinition(
        **{"field_id": "scope1", "name": "scope1", "description": "d", "data_type": FieldDataType.NUMBER,
           "extraction_instructions": "look", "seed_keywords": ["emissions"], **kw}
    )


def _draft(value, raw) -> ExtractionDraft:
    return ExtractionDraft(values=[PeriodValue(value=value, raw_value_text=raw, citations=[
        Citation(doc_id=_DOC.doc_id, doc_type=_DOC.doc_type, quote=raw),
    ])], confidence=0.9)


async def _run(llm, field, *, sink=None, **kw):
    kwargs = {} if sink is None else {"trace_sink": sink}
    return await extract_one_field(
        "Acme", field, documents=[_DOC], documents_by_id={_DOC.doc_id: _DOC}, llm=llm, verifier_llm=llm,
        fuzzy_threshold=0.9, confidence_review_threshold=0.6, **kw, **kwargs,
    )


def _agreeing_llm(fake_llm):
    return fake_llm({
        "ExtractionDraft": [_draft(120, "120 tonnes")],
        "VerifierOutput": [VerifierOutput(agrees=True, confidence=0.9, notes="ok")],
    })


async def test_entry_for_agreeing_field(fake_llm):
    llm, sink = _agreeing_llm(fake_llm), {}
    await _run(llm, _field(), sink=sink)
    e = sink["scope1"]
    assert e["field_id"] == "scope1" and e["grouped"] is False and e["skipped"] is None
    assert e["extractor"]["answer"]["values"][0]["value"] == 120
    assert e["verifier"]["blind"] is False and e["verifier"]["verdict"] is None
    assert e["verifier"]["answer"]["agrees"] is True
    assert (e["adjudicator"], e["vision"]) == (None, None)
    assert e["passages"] and all(set(p) == _KEYS for p in e["passages"])
    positions = [llm.prompts[0].index(_TEXT[p["char_start"]:p["char_end"]]) for p in e["passages"]]
    assert positions == sorted(positions)


async def test_blind_verifier_draft_is_kept(fake_llm):
    llm = fake_llm({
        "ExtractionDraft": [_draft(2.8, "2.8"), _draft(2.794, "2.794")],
        "AdjudicatorOutput": [AdjudicatorOutput(settled=False, notes="unclear")],
    })
    sink = {}
    await _run(llm, _field(high_risk=True), sink=sink)
    v = sink["scope1"]["verifier"]
    assert v["blind"] is True
    assert v["answer"]["values"][0]["value"] == 2.794
    assert v["verdict"]["agrees"] is False
    assert sink["scope1"]["adjudicator"]["answer"]["settled"] is False


async def test_tagged_field_entry(fake_llm):
    row = {"start": "2024-01-01", "end": "2024-12-31", "val": 120, "fy": 2024, "fp": "FY", "form": "10-K",
           "filed": "2025-02-01", "accn": "0001-24-000001"}
    facts = CompanyFactsSource({"facts": {"us-gaap": {"Revenues": {"units": {"USD": [row]}}}}}, "0000000001")
    llm, sink = fake_llm({}), {}
    rows, _, _ = await _run(
        llm, _field(xbrl_tags=["us-gaap:Revenues"]), sink=sink, facts=facts, planned_periods=["2024-12-31"],
    )
    assert rows[0].method == "tagged" and llm.calls == []
    e = sink["scope1"]
    assert (e["skipped"], e["passages"]) == ("tagged", [])
    assert [e[k] for k in ("extractor", "verifier", "adjudicator", "vision")] == [None] * 4


async def test_no_evidence_entry(fake_llm):
    sink = {}
    await _run(fake_llm({}), _field(seed_keywords=["zzzunmatched"]), sink=sink)
    assert sink["scope1"]["skipped"] == "no_evidence"
    assert sink["scope1"]["extractor"] is None


async def test_entry_failure_never_fails_the_field(fake_llm, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("model_dump failed")

    monkeypatch.setattr("arp.extraction.field_graph._trace_entry", boom)
    llm, sink = _agreeing_llm(fake_llm), {}
    rows, needs_review, usages = await _run(llm, _field(), sink=sink)
    assert rows[0].value == 120 and isinstance(needs_review, bool) and usages
    assert sink == {}


async def test_no_sink_changes_nothing(fake_llm):
    with_sink, without = _agreeing_llm(fake_llm), _agreeing_llm(fake_llm)
    assert await _run(with_sink, _field(), sink={}) == await _run(without, _field())
    assert without.calls == with_sink.calls == ["ExtractionDraft", "VerifierOutput"]


_PAGE1 = "Acme Corp sustainability report. Introduction and strategy overview.\n"
_PAGE2 = "Environment table. Spills: 7 incidents in FY2024.\n"


@pytest.fixture
def pdf_doc(tmp_path) -> SourceDocument:
    path = tmp_path / "report.pdf"
    c = canvas.Canvas(str(path))
    for text in (_PAGE1, _PAGE2):
        c.drawString(72, 720, text.strip())
        c.showPage()
    c.save()
    return SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG", full_text=_PAGE1 + _PAGE2,
        local_path=str(path), page_breaks=[0, len(_PAGE1)],
    )


async def _vision_entry(fake_llm, pdf_doc, *, enabled):
    [chunk] = [c for c in chunk_document(pdf_doc) if "Spills" in c.text]
    draft = ExtractionDraft(values=[PeriodValue(
        value=7, raw_value_text="7", period_text="FY2024",
        citations=[Citation(doc_id=pdf_doc.doc_id, doc_type=pdf_doc.doc_type, quote="Spills total seven",
                            passage_id=chunk.chunk_id)],
    )], confidence=0.9)
    reading = PageReading(found=True, figure_text="7", notes="row 3")
    llm = fake_llm({
        "ExtractionDraft": [draft], "VerifierOutput": [VerifierOutput(agrees=True, confidence=0.9, notes="ok")],
        "PageReading": [reading],
    })
    sink = {}
    await extract_one_field(
        "Acme", _field(field_id="spills", seed_keywords=["spills"]), documents=[pdf_doc],
        documents_by_id={pdf_doc.doc_id: pdf_doc}, llm=llm, verifier_llm=llm,
        settings=Settings(hybrid_retrieval_enabled=False, vision_fallback_enabled=enabled),
        fuzzy_threshold=0.92, confidence_review_threshold=0.6, trace_sink=sink,
    )
    return sink["spills"], reading


async def test_vision_answer_recorded(fake_llm, pdf_doc):
    entry, reading = await _vision_entry(fake_llm, pdf_doc, enabled=True)
    assert entry["vision"]["answer"] == reading.model_dump(mode="json")
    assert set(entry["vision"]) == {"model", "prompt_version", "answer"}


async def test_no_vision_when_fallback_off(fake_llm, pdf_doc):
    entry, _ = await _vision_entry(fake_llm, pdf_doc, enabled=False)
    assert entry["vision"] is None
