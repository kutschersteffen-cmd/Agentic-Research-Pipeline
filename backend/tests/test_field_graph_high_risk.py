from arp.extraction.extractor_agent import ExtractionDraft
from arp.extraction.field_graph import extract_one_field
from arp.schemas.common import DocType, SourceDocument
from arp.schemas.datapoints import FieldDataType, FieldDefinition

_DOC = SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG", full_text="We sell shoes.")


async def _run(fake_llm, *, high_risk):
    field = FieldDefinition(
        name="f", description="d", data_type=FieldDataType.NUMBER, extraction_instructions="look",
        seed_keywords=["zzzunmatched"], high_risk=high_risk,
    )
    # a high-risk field's verifier is a blind second extraction, so it needs its own draft
    llm = fake_llm({"ExtractionDraft": [ExtractionDraft(confidence=0.0)] * 2})
    await extract_one_field(
        "Acme", field, documents=[_DOC], documents_by_id={_DOC.doc_id: _DOC}, llm=llm, verifier_llm=llm,
        fuzzy_threshold=0.9, confidence_review_threshold=0.6,
    )
    return llm


async def test_high_risk_field_still_extracts_when_no_keyword_hits(fake_llm):
    assert "ExtractionDraft" in (await _run(fake_llm, high_risk=True)).calls


async def test_low_risk_field_skips_extraction_when_no_keyword_hits(fake_llm):
    assert (await _run(fake_llm, high_risk=False)).calls == []


async def test_gather_evidence_passes_rerank_settings(monkeypatch):
    from arp.config import Settings
    from arp.extraction import field_graph

    seen = []
    monkeypatch.setattr(field_graph, "select_relevant_chunks", lambda *a, **kw: seen.append(kw) or [])
    field = FieldDefinition(
        name="f", description="d", data_type=FieldDataType.NUMBER, extraction_instructions="look",
        seed_keywords=["shoes"], high_risk=True,
    )
    base = {"field": field, "documents": [_DOC]}
    on = Settings(hybrid_retrieval_enabled=False, rerank_enabled=True, rerank_candidates=33, evidence_max_chunks=7)
    off = Settings(hybrid_retrieval_enabled=False, rerank_enabled=False)
    await field_graph._gather_evidence({**base, "settings": on})
    await field_graph._gather_evidence({**base, "settings": off})
    await field_graph._gather_evidence({**base, "settings": None})
    assert (seen[0]["max_chunks"], seen[0]["rerank_candidates"], seen[0]["fallback_to_all"]) == (7, 33, True)
    assert (seen[1]["max_chunks"], seen[1]["rerank_candidates"]) == (12, None)
    assert "max_chunks" not in seen[2] and "rerank_candidates" not in seen[2]
