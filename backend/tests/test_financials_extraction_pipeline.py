from arp.config import Settings
from arp.extraction.financials_extractor_agent import FinancialsExtractionDraft, SpendSectionDraft
from arp.extraction.financials_pipeline import _extract_company_financials
from arp.extraction.financials_verifier_agent import FinancialsVerifierOutput
from arp.extraction.segment_extractor_agent import SegmentDraft, SegmentMetricDraft
from arp.extraction.spend_extractor_agent import AmountMetricDraft
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.ingestion.xbrl import CompanyXbrlFacts, XbrlFact
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
    "We report two reportable segments: Widgets and Gadgets. The Widgets segment designs and sells industrial "
    "widgets. For fiscal year 2025, Widgets segment revenue was $500 million and segment operating income was "
    "$80 million.\n\n"
    "Capital expenditures for fiscal 2025 were $450 million, primarily funding capacity expansion.\n\n"
    "Research and development expense was $120 million in fiscal 2025, primarily for platform engineering."
)


def _doc() -> SourceDocument:
    return SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text=_FILING_TEXT)


async def test_extract_company_financials_single_call_pair(tmp_path, fake_llm):
    doc = _doc()
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")

    draft = FinancialsExtractionDraft(
        currency="USD",
        fiscal_period="FY2025",
        segments=[
            SegmentDraft(
                name="Widgets",
                description="Designs and sells industrial widgets.",
                description_citations=[
                    Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Widgets segment designs and sells industrial widgets")
                ],
                revenue=SegmentMetricDraft(
                    value=500.0,
                    citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Widgets segment revenue was $500 million")],
                ),
                income=SegmentMetricDraft(
                    value=80.0,
                    citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="segment operating income was $80 million")],
                ),
            )
        ],
        capex=SpendSectionDraft(
            total=AmountMetricDraft(
                value=450.0,
                citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Capital expenditures for fiscal 2025 were $450 million")],
            ),
            description="Primarily funding capacity expansion.",
            description_citations=[
                Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="primarily funding capacity expansion")
            ],
        ),
        rnd=SpendSectionDraft(
            total=AmountMetricDraft(
                value=120.0,
                citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Research and development expense was $120 million in fiscal 2025")],
            ),
            description="Primarily for platform engineering.",
            description_citations=[
                Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="primarily for platform engineering")
            ],
        ),
        confidence=0.9,
    )
    verifier = FinancialsVerifierOutput(
        segments_agree=True, capex_agree=True, rnd_agree=True, confidence=0.9,
        segments_notes="", capex_notes="", rnd_notes="",
    )

    llm = fake_llm({"FinancialsExtractionDraft": [draft], "FinancialsVerifierOutput": [verifier]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company_financials(company, registry=registry, llm=llm, settings=_settings(tmp_path))
    record = result.record

    # Exactly one extractor call and one verifier call for all three topics combined.
    assert llm.calls == ["FinancialsExtractionDraft", "FinancialsVerifierOutput"]

    assert len(record.segments) == 1
    assert record.segments[0].revenue.value == 500.0
    assert record.segments[0].grounded is True
    assert record.capex.total.value == 450.0
    assert record.capex.grounded is True
    assert record.rnd.total.value == 120.0
    assert record.rnd.grounded is True
    assert record.needs_review is False


async def test_extract_company_financials_per_section_review_flagging(tmp_path, fake_llm):
    doc = _doc()
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")

    draft = FinancialsExtractionDraft(
        capex=SpendSectionDraft(
            total=AmountMetricDraft(
                value=450.0,
                citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Capital expenditures for fiscal 2025 were $450 million")],
            ),
        ),
        rnd=SpendSectionDraft(
            total=AmountMetricDraft(
                value=999.0,  # wrong figure, verifier will disagree
                citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Research and development expense was $120 million in fiscal 2025")],
            ),
        ),
        confidence=0.7,
    )
    corrected_rnd = SpendSectionDraft(
        total=AmountMetricDraft(
            value=120.0,
            citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Research and development expense was $120 million in fiscal 2025")],
        ),
    )
    verifier = FinancialsVerifierOutput(
        segments_agree=True,
        capex_agree=True,
        rnd_agree=False,
        corrected_rnd=corrected_rnd,
        rnd_notes="Extractor misread the R&D figure as $999M; it's actually $120M.",
        confidence=0.85,
    )

    llm = fake_llm({"FinancialsExtractionDraft": [draft], "FinancialsVerifierOutput": [verifier]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company_financials(company, registry=registry, llm=llm, settings=_settings(tmp_path))
    record = result.record

    # Capex section was fine and shouldn't be penalized by the R&D disagreement.
    assert record.capex.total.value == 450.0
    assert record.rnd.total.value == 120.0  # verifier's correction wins
    assert record.needs_review is True


async def test_extract_company_financials_no_evidence_skips_llm(tmp_path, fake_llm):
    doc = SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text="We sell shoes.")
    company = CompanyRef(company_id="c1", name="Shoe Co", ticker="SHOE")

    llm = fake_llm({})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company_financials(company, registry=registry, llm=llm, settings=_settings(tmp_path))
    assert result.record.segments == []
    assert result.record.capex.total.value is None
    assert result.record.needs_review is False
    assert llm.calls == []


class _FakeXbrlSource:
    """Stands in for XbrlFactSource: returns a fixed CompanyXbrlFacts
    without any network access, mirroring how EdgarDocumentSource itself
    is faked in test_edgar_cache.py."""

    def __init__(self, facts: CompanyXbrlFacts | None):
        self._facts = facts
        self.resolve_calls: list[tuple] = []

    async def resolve_cik(self, cik, ticker):
        self.resolve_calls.append((cik, ticker))
        return cik or "320193"

    async def fetch_capex_rnd_revenue(self, company_id, cik):
        return self._facts


async def test_xbrl_overlay_replaces_capex_total_but_not_llm_description(tmp_path, fake_llm):
    """The XBRL Path 0: when SEC's structured data has a CapEx figure, it
    replaces the LLM-extracted total (a hard fact outranks an LLM's read
    of prose) but must NOT wipe out the LLM-sourced description/segments,
    which XBRL has no equivalent of."""
    doc = _doc()
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME", cik="320193")

    draft = FinancialsExtractionDraft(
        capex=SpendSectionDraft(
            total=AmountMetricDraft(
                value=450.0,
                citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Capital expenditures for fiscal 2025 were $450 million")],
            ),
            description="Primarily funding capacity expansion.",
            description_citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="primarily funding capacity expansion")],
        ),
        rnd=SpendSectionDraft(
            total=AmountMetricDraft(
                value=120.0,
                citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Research and development expense was $120 million in fiscal 2025")],
            ),
        ),
        confidence=0.9,
    )
    verifier = FinancialsVerifierOutput(segments_agree=True, capex_agree=True, rnd_agree=True, confidence=0.9)
    llm = fake_llm({"FinancialsExtractionDraft": [draft], "FinancialsVerifierOutput": [verifier]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    # XBRL disagrees slightly with the LLM's read (340.0 vs 450.0) -- the
    # structured fact must win. Only capex is present in XBRL; R&D falls
    # through untouched to the LLM-extracted value.
    xbrl_facts = CompanyXbrlFacts(
        company_id="c1",
        cik="320193",
        capex=XbrlFact(
            tag="PaymentsToAcquirePropertyPlantAndEquipment", value=340000000, unit="USD",
            fiscal_year=2025, fiscal_period="FY", form="10-K", filed="2026-02-01", accession="0001-25-000001",
        ),
        rnd=None,
    )
    xbrl_source = _FakeXbrlSource(xbrl_facts)

    result = await _extract_company_financials(
        company, registry=registry, llm=llm, settings=_settings(tmp_path), xbrl_source=xbrl_source
    )
    record = result.record

    assert record.capex.total.value == 340000000  # XBRL wins over the LLM's 450.0
    assert record.capex.grounded is True
    assert record.capex.confidence == 1.0
    assert record.capex.description == "Primarily funding capacity expansion."  # LLM description preserved
    assert record.rnd.total.value == 120.0  # untouched -- XBRL had no R&D fact
    assert xbrl_source.resolve_calls == [("320193", "ACME")]


async def test_xbrl_overlay_is_noop_when_no_facts_found(tmp_path, fake_llm):
    doc = _doc()
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")
    draft = FinancialsExtractionDraft(
        capex=SpendSectionDraft(
            total=AmountMetricDraft(
                value=450.0,
                citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Capital expenditures for fiscal 2025 were $450 million")],
            ),
        ),
        confidence=0.9,
    )
    verifier = FinancialsVerifierOutput(segments_agree=True, capex_agree=True, rnd_agree=True, confidence=0.9)
    llm = fake_llm({"FinancialsExtractionDraft": [draft], "FinancialsVerifierOutput": [verifier]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    xbrl_source = _FakeXbrlSource(None)  # e.g. no CIK resolvable, or a 404 from SEC

    result = await _extract_company_financials(
        company, registry=registry, llm=llm, settings=_settings(tmp_path), xbrl_source=xbrl_source
    )
    assert result.record.capex.total.value == 450.0  # LLM value stands, untouched
