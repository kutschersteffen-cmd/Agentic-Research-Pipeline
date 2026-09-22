"""A segment description the model wrote but never cited must not be
reported as grounded.

`build_segments` used to roll a description with zero citations up as
grounded (`... if description_citations else True`), while the sibling
`spend_aggregator._build_category` rolled the identical case up as
ungrounded. Because `segment_grounded` feeds `any_needs_review`, an
uncited description was not only labelled verified but also never routed
to the review queue -- the one outcome the programmatic grounding pass
exists to prevent.
"""

from arp.extraction.segment_aggregator import build_segments
from arp.extraction.segment_extractor_agent import SegmentDraft, SegmentMetricDraft
from arp.schemas.common import Citation, DocType, SourceDocument

_QUOTE = "Widgets segment revenue was $500 million."
_DOC = SourceDocument(company_id="acme", doc_type=DocType.ANNUAL_REPORT_10K, title="Annual Report", full_text=_QUOTE)
_DOCS = {_DOC.doc_id: _DOC}


def _cite(quote: str = _QUOTE) -> Citation:
    return Citation(doc_id=_DOC.doc_id, doc_type=_DOC.doc_type, quote=quote)


def _build(segment: SegmentDraft):
    return build_segments(
        [segment],
        0.9,
        verifier_agrees=True,
        corrected_segments=None,
        verifier_confidence=0.9,
        verifier_notes="",
        documents_by_id=_DOCS,
        fuzzy_threshold=0.9,
        confidence_review_threshold=0.6,
    )


def test_uncited_description_is_not_grounded_and_needs_review():
    segments, needs_review = _build(
        SegmentDraft(
            name="Widgets",
            description="Designs and sells industrial widgets.",  # asserted, never cited
            description_citations=[],
            revenue=SegmentMetricDraft(value=500.0, citations=[_cite()]),
        )
    )

    assert segments[0].grounded is False
    assert needs_review is True


def test_absent_description_is_still_grounded():
    # Nothing to ground is not the same as something ungrounded: a segment
    # that simply has no description must not be dragged into review.
    segments, needs_review = _build(
        SegmentDraft(
            name="Widgets",
            description=None,
            description_citations=[],
            revenue=SegmentMetricDraft(value=500.0, citations=[_cite()]),
        )
    )

    assert segments[0].grounded is True
    assert needs_review is False


def test_cited_description_that_grounds_is_grounded():
    segments, needs_review = _build(
        SegmentDraft(
            name="Widgets",
            description="Revenue was $500 million.",
            description_citations=[_cite()],
            revenue=SegmentMetricDraft(value=500.0, citations=[_cite()]),
        )
    )

    assert segments[0].grounded is True
    assert needs_review is False


def test_description_citing_a_quote_absent_from_the_document_is_not_grounded():
    segments, needs_review = _build(
        SegmentDraft(
            name="Widgets",
            description="Margins expanded sharply.",
            description_citations=[_cite("Margins expanded sharply in every region")],
            revenue=SegmentMetricDraft(value=500.0, citations=[_cite()]),
        )
    )

    assert segments[0].description_citations[0].grounded is False
    assert segments[0].grounded is False
    assert needs_review is True


def test_uncited_metric_value_is_not_grounded():
    # The metric roll-up shares the rule: a real value with no citation is
    # ungrounded, an absent value is trivially fine.
    segments, needs_review = _build(
        SegmentDraft(
            name="Widgets",
            description=None,
            description_citations=[],
            revenue=SegmentMetricDraft(value=500.0, citations=[]),
        )
    )

    assert segments[0].revenue.grounded is False
    assert needs_review is True
