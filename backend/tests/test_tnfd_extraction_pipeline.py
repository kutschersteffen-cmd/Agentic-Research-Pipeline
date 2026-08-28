from arp.config import Settings
from arp.extraction.tnfd_extractor_agent import DisclosureDraft, TNFDExtractionDraft
from arp.extraction.tnfd_pipeline import _extract_company_tnfd
from arp.extraction.tnfd_verifier_agent import TNFDVerifierOutput
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
    "TNFD Nature-Related Disclosures\n\n"
    "Governance: The Board reviews nature-related dependencies, impacts, risks and opportunities on a "
    "quarterly basis as part of its overall risk oversight process.\n\n"
    "Strategy: We identified deforestation risk in our upstream palm oil supply chain as a material "
    "nature-related risk over the medium term."
)


def _doc() -> SourceDocument:
    return SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="Sustainability Report", full_text=_FILING_TEXT)


def _agreeing_verifier(**overrides) -> TNFDVerifierOutput:
    defaults = dict(
        disclosures_agree=True,
        core_global_metrics_agree=True,
        sector_metrics_agree=True,
        sector_leap_considerations_agree=True,
        general_requirements_agree=True,
        confidence=0.9,
    )
    defaults.update(overrides)
    return TNFDVerifierOutput(**defaults)


async def test_extract_company_tnfd_single_call_pair(tmp_path, fake_llm):
    doc = _doc()
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")

    draft = TNFDExtractionDraft(
        disclosures=[
            DisclosureDraft(
                recommendation_id="governance.A",
                disclosed=True,
                summary="The Board reviews nature-related risks quarterly.",
                summary_citations=[
                    Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="The Board reviews nature-related dependencies, impacts, risks and opportunities on a quarterly basis")
                ],
                materiality_basis="double",
            ),
            DisclosureDraft(
                recommendation_id="strategy.A",
                disclosed=True,
                summary="Identified deforestation risk in upstream palm oil supply chain.",
                summary_citations=[
                    Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="We identified deforestation risk in our upstream palm oil supply chain")
                ],
                materiality_basis="double",
            ),
        ],
        confidence=0.9,
    )
    verifier = _agreeing_verifier()

    llm = fake_llm({"TNFDExtractionDraft": [draft], "TNFDVerifierOutput": [verifier]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company_tnfd(
        company, run_id="run1", as_of="FY2025", registry=registry, llm=llm, settings=_settings(tmp_path)
    )
    record = result.record

    # Exactly one extractor call and one verifier call for the whole combined extraction.
    assert llm.calls == ["TNFDExtractionDraft", "TNFDVerifierOutput"]

    assert len(record.disclosures) == 2
    assert record.disclosures[0].grounded is True
    assert record.disclosures[1].grounded is True
    assert len(record.missing_recommendations) == 12
    assert record.needs_review is False


async def test_extract_company_tnfd_verifier_disagreement_forces_review(tmp_path, fake_llm):
    doc = _doc()
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")

    draft = TNFDExtractionDraft(
        disclosures=[
            DisclosureDraft(recommendation_id="governance.A", disclosed=False),
        ],
        confidence=0.7,
    )
    corrected = [
        DisclosureDraft(
            recommendation_id="governance.A",
            disclosed=True,
            summary="The Board reviews nature-related risks quarterly.",
            summary_citations=[
                Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="The Board reviews nature-related dependencies, impacts, risks and opportunities on a quarterly basis")
            ],
        )
    ]
    verifier = _agreeing_verifier(
        disclosures_agree=False, corrected_disclosures=corrected, disclosures_notes="Extractor missed the governance disclosure.",
        confidence=0.85,
    )

    llm = fake_llm({"TNFDExtractionDraft": [draft], "TNFDVerifierOutput": [verifier]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company_tnfd(
        company, run_id="run1", as_of="FY2025", registry=registry, llm=llm, settings=_settings(tmp_path)
    )
    record = result.record

    assert record.disclosures[0].disclosed is True  # verifier's correction wins
    assert record.needs_review is True


async def test_extract_company_tnfd_no_evidence_skips_llm(tmp_path, fake_llm):
    doc = SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="Sustainability Report", full_text="We sell shoes.")
    company = CompanyRef(company_id="c1", name="Shoe Co", ticker="SHOE")

    llm = fake_llm({})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company_tnfd(
        company, run_id="run1", as_of="FY2025", registry=registry, llm=llm, settings=_settings(tmp_path)
    )
    assert result.record.disclosures == []
    assert result.record.needs_review is False
    assert llm.calls == []
