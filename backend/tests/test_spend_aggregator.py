from arp.extraction.spend_aggregator import build_spend_record
from arp.extraction.spend_extractor_agent import AmountMetricDraft, SpendExtractionDraft
from arp.extraction.spend_verifier_agent import SpendVerifierOutput
from arp.schemas.common import Citation, DocType, SourceDocument
from arp.schemas.spend import SpendTopic

_QUOTE = "Total CapEx was $500 million, of which $200 million was green capex."
_DOC = SourceDocument(company_id="acme", doc_type=DocType.SUSTAINABILITY_REPORT, title="Sustainability Report", full_text=_QUOTE)
_DOCS = {_DOC.doc_id: _DOC}


def _draft(**overrides):
    defaults = dict(
        total=AmountMetricDraft(value=500.0, citations=[Citation(doc_id=_DOC.doc_id, doc_type=_DOC.doc_type, quote=_QUOTE)]),
        description="Green capex spend.",
        description_citations=[Citation(doc_id=_DOC.doc_id, doc_type=_DOC.doc_type, quote=_QUOTE)],
        confidence=0.85,
    )
    defaults.update(overrides)
    return SpendExtractionDraft(**defaults)


def test_description_citations_preserved_when_verifier_disagrees_about_total_only():
    # Verifier corrects only the total, leaves the description untouched --
    # the description's original, fully-cited text must keep its citations
    # and stay grounded, not get its citations wiped just because *some*
    # part of the record was disputed.
    draft = _draft()
    verifier = SpendVerifierOutput(
        agrees=False,
        corrected_total=AmountMetricDraft(value=550.0, citations=[Citation(doc_id=_DOC.doc_id, doc_type=_DOC.doc_type, quote=_QUOTE)]),
        confidence=0.8,
        notes="Total was understated.",
    )

    record, needs_review = build_spend_record(SpendTopic.CAPEX, "acme", None, "Acme", draft, verifier, _DOCS, 0.9, 0.6)

    assert record.description == "Green capex spend."
    assert len(record.description_citations) == 1
    assert record.description_citations[0].grounded is True
    assert needs_review is True  # verifier disagreement always routes to review


def test_verifier_corrected_description_with_no_citations_is_not_grounded():
    draft = _draft()
    verifier = SpendVerifierOutput(agrees=False, corrected_description="Actually mostly maintenance capex.", confidence=0.7, notes="Description was wrong.")

    record, _ = build_spend_record(SpendTopic.CAPEX, "acme", None, "Acme", draft, verifier, _DOCS, 0.9, 0.6)

    assert record.description == "Actually mostly maintenance capex."
    assert record.description_citations == []
    assert record.grounded is False


def test_verifier_corrected_description_with_citations_is_grounded():
    # The combined financials pipeline re-wraps a full SpendSectionDraft
    # (financials_aggregator.py), which does carry citations for a
    # corrected description -- those must be used, not discarded.
    draft = _draft()
    verifier = SpendVerifierOutput(
        agrees=False,
        corrected_description="Green capex spend, revised.",
        corrected_description_citations=[Citation(doc_id=_DOC.doc_id, doc_type=_DOC.doc_type, quote=_QUOTE)],
        confidence=0.8,
        notes="Wording was imprecise.",
    )

    record, _ = build_spend_record(SpendTopic.CAPEX, "acme", None, "Acme", draft, verifier, _DOCS, 0.9, 0.6)

    assert record.description == "Green capex spend, revised."
    assert len(record.description_citations) == 1
    assert record.description_citations[0].grounded is True
