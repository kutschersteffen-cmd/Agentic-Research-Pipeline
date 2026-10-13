from __future__ import annotations

import asyncio

from arp.config import Settings
from arp.golden_set import retrieval
from arp.golden_set.retrieval import GoldSpan, gold_spans, hit_rank, recall_at, run_retrieval_eval
from arp.schemas.common import CompanyRef, DocType, DocumentChunk, SourceDocument
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition
from arp.schemas.review import DecisionKind, DecisionReason, ReviewDecision, field_item_key

ISSUER = "lei:ACME:1"


def _chunk(doc_id, start, end):
    return DocumentChunk(doc_id=doc_id, company_id="acme", doc_type=DocType.SUSTAINABILITY_REPORT, text="x", char_start=start, char_end=end)


def _cite(doc_id, start, end, grounded=True, span_text="t"):
    return {"doc_id": doc_id, "doc_type": "sustainability_report", "quote": "q", "grounded": grounded, "char_start": start,
            "char_end": end, "span_text": span_text}


def _decision(field_id, kind, reason, *, corrected=None, citation=None):
    return ReviewDecision(
        item_key=field_item_key(ISSUER, field_id, "unspecified"), decision=kind, reason_code=reason, reviewer="r",
        user_id="u", role="reviewer", corrected_value=corrected, correction_citation=citation, snapshot_id="s", step="first",
    )


class StubStore:
    def __init__(self, rows, tmp_path=None):
        self.rows, self.tmp_path = rows, tmp_path

    def read_results(self, run_id):
        return self.rows

    def load_companies(self, run_id):
        return [CompanyRef(company_id="acme", name="Acme")]

    def run_dir(self, run_id):
        return self.tmp_path


def test_hit_rank_counts_any_overlap_in_the_same_document():
    evidence = [_chunk("other", 0, 500), _chunk("doc", 0, 100), _chunk("doc", 90, 400)]
    assert hit_rank(evidence, GoldSpan("acme", "f", "doc", 95, 120, None)) == 1  # partial overlap is a hit
    assert hit_rank(evidence, GoldSpan("acme", "f", "doc", 400, 450, None)) is None  # touching the end is not
    assert hit_rank(evidence, GoldSpan("acme", "f", "elsewhere", 0, 10, None)) is None
    assert hit_rank([], GoldSpan("acme", "f", "doc", 0, 10, None)) is None


def test_recall_at_k():
    assert recall_at([0, 4, 5, None], 5) == 0.5
    assert recall_at([0, 4, 5, None], 6) == 0.75
    assert recall_at([], 5) is None


def test_gold_spans_take_final_approvals_and_grounded_corrections_only():
    rows = [{"company_id": "acme", "issuer_key": ISSUER, "fields": [
        {"field_id": "scope1", "citations": [_cite("d1", 10, 20), _cite("d1", 10, 20), _cite("d1", 50, 60, grounded=False)]},
        {"field_id": "scope2", "citations": [_cite("d1", 70, 80)]},
        {"field_id": "scope3", "citations": [_cite("d1", 90, 95)]},
        {"field_id": "water", "citations": [_cite("d1", 99, 101)]},
    ]}]
    decisions = [
        _decision("scope1", DecisionKind.APPROVE, DecisionReason.CONFIRMED),
        _decision("scope2", DecisionKind.CORRECT, DecisionReason.WRONG_VALUE, corrected={"value": 5},
                  citation=_cite("d2", 300, 310)),
        _decision("scope3", DecisionKind.REJECT, DecisionReason.NOT_DISCLOSED),
        # water: never reviewed
    ]
    assert gold_spans(StubStore(rows), "run", decisions) == [
        GoldSpan("acme", "scope1", "d1", 10, 20, "t"),  # the duplicate and the ungrounded citation are dropped
        GoldSpan("acme", "scope2", "d2", 300, 310, "t"),  # the reviewer's citation, not the extractor's
    ]


def test_run_replays_field_evidence_and_reports_recall(tmp_path, monkeypatch):
    filler = "Our revenue grew strongly this year. " * 300  # several chunks with no keyword in them
    text = filler + "Scope 1 emissions were 1,234 tonnes CO2e in 2025. " + filler
    start = text.index("Scope 1")
    doc = SourceDocument(doc_id="d1", company_id="acme", doc_type=DocType.SUSTAINABILITY_REPORT, title="ar.pdf", full_text=text)

    class Registry:
        async def fetch_all(self, company):
            return [doc]

    monkeypatch.setattr(retrieval, "_registry", lambda documents_dir, settings: Registry())
    field = FieldDefinition(field_id="scope1", name="Scope 1", description="Scope 1 GHG emissions", data_type=FieldDataType.NUMBER,
                            extraction_instructions="", seed_keywords=["scope 1", "emissions"])
    (tmp_path / "schema.json").write_text(DataPointSchema(name="ghg", fields=[field]).model_dump_json())
    rows = [{"company_id": "acme", "issuer_key": ISSUER, "fields": [
        {"field_id": "scope1", "citations": [
            _cite("d1", start, start + 40, span_text=text[start:start + 40]),
            _cite("d1", 100, 140, span_text=text[100:140]),
            _cite("d1", 0, 40, span_text="text from an older parse"),  # offsets moved: stale, not a miss
            _cite("gone", 0, 40, span_text=text[:40]),  # document no longer fetched: stale too
        ]},
    ]}]
    settings = Settings(hybrid_retrieval_enabled=False, rerank_enabled=False)
    report = asyncio.run(run_retrieval_eval(
        StubStore(rows, tmp_path), "run", [_decision("scope1", DecisionKind.APPROVE, DecisionReason.CONFIRMED)],
        documents_dir=tmp_path, settings=settings,
    ))
    assert report["gold_spans"] == 2 and report["stale_spans"] == 2 and report["fields_ranked"] == 1
    assert report["recall_at_5"] == 0.5  # the keyword chunk is found; the span in filler text is not
    assert [(m["char_start"], m["char_end"]) for m in report["misses"]] == [(100, 140)]
    assert report["settings"]["hybrid_retrieval_enabled"] is False
