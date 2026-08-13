from arp.config import Settings
from arp.extraction.segment_extractor_agent import SegmentDraft, SegmentExtractionDraft, SegmentMetricDraft
from arp.extraction.segment_pipeline import _extract_company_segments
from arp.extraction.segment_verifier_agent import SegmentVerifierOutput
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument


class _FixedDocSource(DocumentSource):
    name = "fixed"

    def __init__(self, docs):
        self._docs = docs

    async def fetch(self, company, doc_types=None):
        return self._docs


def _settings(tmp_path) -> Settings:
    return Settings(
        anthropic_api_key="unused",
        runs_dir=tmp_path / "runs",
        documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache",
        discovery_state_dir=tmp_path / "disc",
    )


_FILING_TEXT = (
    "Note 14. Segment Reporting\n\n"
    "We report two reportable segments: Widgets and Gadgets. The Widgets "
    "segment designs and sells industrial widgets. The Gadgets segment "
    "designs and sells consumer gadgets.\n\n"
    "For fiscal year 2025, Widgets segment revenue was $500 million and "
    "segment operating income was $80 million. Gadgets segment revenue "
    "was $300 million and segment operating income was $40 million. "
    "Segment assets are not disclosed."
)


def _doc() -> SourceDocument:
    return SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text=_FILING_TEXT)


async def test_extract_company_segments_grounded_not_flagged(tmp_path, fake_llm):
    doc = _doc()
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")

    draft = SegmentExtractionDraft(
        segments=[
            SegmentDraft(
                name="Widgets",
                description="Designs and sells industrial widgets.",
                description_citations=[
                    Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Widgets segment designs and sells industrial widgets")
                ],
                revenue=SegmentMetricDraft(
                    value=500.0,
                    raw_value_text="$500 million",
                    citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Widgets segment revenue was $500 million")],
                ),
                income=SegmentMetricDraft(
                    value=80.0,
                    raw_value_text="$80 million",
                    citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="segment operating income was $80 million")],
                ),
                currency="USD",
                fiscal_period="FY2025",
            ),
            SegmentDraft(
                name="Gadgets",
                description="Designs and sells consumer gadgets.",
                description_citations=[
                    Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Gadgets segment designs and sells consumer gadgets")
                ],
                revenue=SegmentMetricDraft(
                    value=300.0,
                    raw_value_text="$300 million",
                    citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Gadgets segment revenue was $300 million")],
                ),
                income=SegmentMetricDraft(
                    value=40.0,
                    raw_value_text="$40 million",
                    citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="segment operating income was $40 million")],
                ),
                currency="USD",
                fiscal_period="FY2025",
            ),
        ],
        confidence=0.9,
    )
    verifier = SegmentVerifierOutput(agrees=True, confidence=0.9, notes="Matches the cited text.")

    llm = fake_llm({"SegmentExtractionDraft": [draft], "SegmentVerifierOutput": [verifier]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company_segments(company, registry=registry, llm=llm, settings=_settings(tmp_path))
    record = result.record
    assert len(record.segments) == 2
    widgets = next(s for s in record.segments if s.name == "Widgets")
    assert widgets.revenue.value == 500.0
    assert widgets.revenue.grounded is True
    assert widgets.assets.value is None
    assert widgets.grounded is True
    assert record.needs_review is False


async def test_extract_company_segments_verifier_disagreement_flags_review(tmp_path, fake_llm):
    doc = _doc()
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")

    draft = SegmentExtractionDraft(
        segments=[
            SegmentDraft(
                name="Widgets",
                revenue=SegmentMetricDraft(
                    value=500.0,
                    citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Widgets segment revenue was $500 million")],
                ),
            )
        ],
        confidence=0.7,
    )
    corrected = SegmentDraft(
        name="Widgets",
        revenue=SegmentMetricDraft(
            value=500.0,
            raw_value_text="corrected to segment revenue, not total revenue",
            citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Widgets segment revenue was $500 million")],
        ),
    )
    verifier = SegmentVerifierOutput(
        agrees=False, corrected_segments=[corrected], confidence=0.85, notes="Extractor mislabeled the raw value text."
    )

    llm = fake_llm({"SegmentExtractionDraft": [draft], "SegmentVerifierOutput": [verifier]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company_segments(company, registry=registry, llm=llm, settings=_settings(tmp_path))
    assert result.record.needs_review is True
    assert result.record.segments[0].revenue.raw_value_text == "corrected to segment revenue, not total revenue"


async def test_extract_company_segments_no_evidence_skips_llm(tmp_path, fake_llm):
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text="We sell shoes.")
    company = CompanyRef(company_id="c1", name="Shoe Co", ticker="SHOE")

    llm = fake_llm({})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company_segments(company, registry=registry, llm=llm, settings=_settings(tmp_path))
    assert result.record.segments == []
    assert result.record.needs_review is False
    assert llm.calls == []


async def test_extract_company_segments_ungrounded_citation_flags_review(tmp_path, fake_llm):
    doc = _doc()
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")

    draft = SegmentExtractionDraft(
        segments=[
            SegmentDraft(
                name="Widgets",
                revenue=SegmentMetricDraft(
                    value=500.0,
                    citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="this text does not appear in the filing at all")],
                ),
            )
        ],
        confidence=0.9,
    )
    verifier = SegmentVerifierOutput(agrees=True, confidence=0.9, notes="")

    llm = fake_llm({"SegmentExtractionDraft": [draft], "SegmentVerifierOutput": [verifier]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company_segments(company, registry=registry, llm=llm, settings=_settings(tmp_path))
    assert result.record.segments[0].revenue.grounded is False
    assert result.record.segments[0].grounded is False
    assert result.record.needs_review is True
