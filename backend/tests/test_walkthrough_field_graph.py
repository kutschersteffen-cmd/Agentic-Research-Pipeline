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
_KEYS = {"doc_id", "char_start", "char_end", "section", "scores"}  # scores: why-this-evidence spec


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
    assert set(entry["vision"]) == {"model", "prompt_version", "answer", "input_tokens", "output_tokens", "cost_usd"}  # usage: step-timing spec


async def test_no_vision_when_fallback_off(fake_llm, pdf_doc):
    entry, _ = await _vision_entry(fake_llm, pdf_doc, enabled=False)
    assert entry["vision"] is None


# --- why-this-evidence spec: how the evidence was ranked ---

_LONG = "\n\n".join(f"Section {i}. " + "Scope 1 emissions were reported for the year. " * (75 - i * 3) for i in range(16))
_LONG_DOC = SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG", full_text=_LONG)


async def _run_long(llm, sink):
    return await extract_one_field(
        "Acme", _field(), documents=[_LONG_DOC], documents_by_id={_LONG_DOC.doc_id: _LONG_DOC}, llm=llm,
        verifier_llm=llm, fuzzy_threshold=0.9, confidence_review_threshold=0.6, trace_sink=sink,
    )


async def test_entry_records_retrieval(fake_llm):  # AC-14, AC-15
    sink = {}
    await _run(_agreeing_llm(fake_llm), _field(), sink=sink)
    e = sink["scope1"]
    assert set(e["retrieval"]) == {"method", "reranked", "candidates"}
    assert all(isinstance(p["scores"], dict) for p in e["passages"])


async def test_entry_records_three_near_misses(fake_llm):  # AC-16
    assert len(chunk_document(_LONG_DOC, keywords=["emissions"])) > 13
    sink = {}
    await _run_long(_agreeing_llm(fake_llm), sink)
    near = sink["scope1"]["near_misses"]
    assert len(near) == 3
    assert all(set(n) == _KEYS for n in near)


async def test_grouped_entry_keeps_source_scores(fake_llm):  # AC-17, AC-18
    from arp.llm.base import LLMUsage

    chunks = chunk_document(_DOC, keywords=["emissions"])
    explain = {"method": "bm25", "reranked": False, "candidates": 1, "near_miss_chunks": [],
               "scores": {c.chunk_id: {"bm25": 1.5} for c in chunks}}
    llm, sink = _agreeing_llm(fake_llm), {}
    await _run(llm, _field(), sink=sink, grouped=(_draft(120, "120 tonnes"), chunks, LLMUsage(model="m")),
               grouped_explain=explain)
    e = sink["scope1"]
    assert [p["scores"] for p in e["passages"]] == [{"bm25": 1.5}] * len(chunks)
    assert e["near_misses"] == []


def test_merge_evidence_records_each_chunks_source():  # AC-17: the ranking a shared passage came from
    from arp.extraction.field_graph import merge_evidence

    a, b = chunk_document(_DOC), chunk_document(_LONG_DOC)[:2]
    source: dict = {}
    merged = merge_evidence([a, b], 10, source)
    assert merged == merge_evidence([a, b], 10)
    assert {c.chunk_id: source[c.chunk_id] for c in merged} == {**{c.chunk_id: 0 for c in a}, **{c.chunk_id: 1 for c in b}}


async def test_recording_changes_no_value(fake_llm, monkeypatch):  # AC-34
    from arp.extraction import field_graph

    recorded, _, _ = await _run_long(_agreeing_llm(fake_llm), {})
    real = field_graph.select_relevant_chunks
    monkeypatch.setattr(field_graph, "select_relevant_chunks", lambda *a, **kw: real(*a, **{**kw, "explain": None}))
    plain, _, _ = await _run_long(_agreeing_llm(fake_llm), {})
    assert [f.model_dump() for f in recorded] == [f.model_dump() for f in plain]


# --- step-timing spec: time per node and usage per call ---

async def test_entry_records_node_seconds(fake_llm):  # AC-1
    sink = {}
    await _run(_agreeing_llm(fake_llm), _field(), sink=sink)
    seconds = sink["scope1"]["seconds"]
    assert set(seconds) == {"try_tagged", "gather_evidence", "extract", "verify", "aggregate"}
    assert all(isinstance(s, float) and s >= 0 and round(s, 2) == s for s in seconds.values())


async def test_calls_record_usage(fake_llm):  # AC-3, AC-4, AC-5 (the fake client reports 10 in / 10 out)
    from arp.llm.base import LLMUsage
    from arp.orchestration.cost_tracker import estimate_cost_usd

    sink = {}
    await _run(_agreeing_llm(fake_llm), _field(), sink=sink)
    for step in ("extractor", "verifier"):
        call = sink["scope1"][step]
        assert (call["input_tokens"], call["output_tokens"]) == (10, 10)
        assert call["cost_usd"] == round(estimate_cost_usd(call["model"], LLMUsage(input_tokens=10, output_tokens=10)), 6)


async def test_timing_changes_no_value(fake_llm):  # AC-6
    with_sink, _, _ = await _run(_agreeing_llm(fake_llm), _field(), sink={})
    without, _, _ = await _run(_agreeing_llm(fake_llm), _field())
    assert [f.model_dump() for f in with_sink] == [f.model_dump() for f in without]


async def test_tally_counts_unchanged_by_the_sink(fake_llm, monkeypatch):  # AC-2
    from arp.orchestration import step_tally

    def counted(sink):
        tally = step_tally._Tally()
        monkeypatch.setattr(step_tally, "_current", step_tally.ContextVar("t", default=tally))
        return tally

    a = counted(None)
    await _run(_agreeing_llm(fake_llm), _field(), sink={})
    b = counted(None)
    await _run(_agreeing_llm(fake_llm), _field())
    assert a.counts == b.counts and a.counts


async def test_a_node_run_twice_adds_up(monkeypatch):  # AC-19
    import pytest

    from arp.orchestration import step_tally
    from arp.walkthrough.trace import field_entry

    class Graph:
        async def astream(self, state, stream_mode):
            for node in ("verify", "verify"):
                yield "updates", {node: {}}
            yield "values", state

    import itertools

    clock = itertools.chain([0.0, 0.3, 0.7], itertools.repeat(0.7))  # time is global: the event loop reads it too
    monkeypatch.setattr(step_tally.time, "monotonic", lambda: next(clock))
    seen: dict = {}
    await step_tally.run_graph(Graph(), {"seen": seen})
    assert seen["seconds"]["verify"] == pytest.approx(0.7)
    assert field_entry("f", seconds=seen["seconds"])["seconds"]["verify"] == 0.7
