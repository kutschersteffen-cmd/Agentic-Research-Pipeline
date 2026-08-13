from arp.config import Settings
from arp.extraction.spend_extractor_agent import AmountMetricDraft, SpendCategoryDraft, SpendExtractionDraft
from arp.extraction.spend_pipeline import _extract_company_spend
from arp.extraction.spend_verifier_agent import SpendVerifierOutput
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.schemas.spend import SpendTopic


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


_CAPEX_TEXT = (
    "Capital expenditures for fiscal 2025 were $450 million, primarily funding capacity expansion at our "
    "manufacturing facilities and continued investment in capitalized software for our logistics platform."
)


def _doc(text: str) -> SourceDocument:
    return SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="10-K", full_text=text)


async def test_extract_company_capex_grounded_not_flagged(tmp_path, fake_llm):
    doc = _doc(_CAPEX_TEXT)
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")

    draft = SpendExtractionDraft(
        total=AmountMetricDraft(
            value=450.0,
            raw_value_text="$450 million",
            citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Capital expenditures for fiscal 2025 were $450 million")],
        ),
        description="Primarily funding capacity expansion at manufacturing facilities and capitalized software for the logistics platform.",
        description_citations=[
            Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="primarily funding capacity expansion at our manufacturing facilities")
        ],
        currency="USD",
        fiscal_period="FY2025",
        confidence=0.9,
    )
    verifier = SpendVerifierOutput(agrees=True, confidence=0.9, notes="Matches the cited text.")

    llm = fake_llm({"SpendExtractionDraft": [draft], "SpendVerifierOutput": [verifier]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company_spend(SpendTopic.CAPEX, company, registry=registry, llm=llm, settings=_settings(tmp_path))
    record = result.record
    assert record.topic == SpendTopic.CAPEX
    assert record.total.value == 450.0
    assert record.total.grounded is True
    assert record.grounded is True
    assert record.needs_review is False


async def test_extract_company_rnd_verifier_disagreement_flags_review(tmp_path, fake_llm):
    doc = _doc("R&D expense was $120 million in fiscal 2025, primarily for AI platform research.")
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")

    draft = SpendExtractionDraft(
        total=AmountMetricDraft(
            value=120.0,
            citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="R&D expense was $120 million in fiscal 2025")],
        ),
        confidence=0.7,
    )
    verifier = SpendVerifierOutput(
        agrees=False,
        corrected_total=AmountMetricDraft(
            value=120.0,
            raw_value_text="confirmed $120 million, correctly the total R&D expense line",
            citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="R&D expense was $120 million in fiscal 2025")],
        ),
        corrected_description="Primarily for AI platform research.",
        confidence=0.85,
        notes="Extractor missed the qualitative description of what R&D is funding.",
    )

    llm = fake_llm({"SpendExtractionDraft": [draft], "SpendVerifierOutput": [verifier]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company_spend(SpendTopic.RND, company, registry=registry, llm=llm, settings=_settings(tmp_path))
    assert result.record.needs_review is True
    assert result.record.description == "Primarily for AI platform research."


async def test_extract_company_spend_no_evidence_skips_llm(tmp_path, fake_llm):
    doc = _doc("We sell shoes.")
    company = CompanyRef(company_id="c1", name="Shoe Co", ticker="SHOE")

    llm = fake_llm({})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company_spend(SpendTopic.CAPEX, company, registry=registry, llm=llm, settings=_settings(tmp_path))
    assert result.record.total.value is None
    assert result.record.needs_review is False
    assert llm.calls == []


async def test_extract_company_capex_categories_grounded(tmp_path, fake_llm):
    doc = _doc(_CAPEX_TEXT)
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")

    draft = SpendExtractionDraft(
        total=AmountMetricDraft(
            value=450.0,
            citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="Capital expenditures for fiscal 2025 were $450 million")],
        ),
        categories=[
            SpendCategoryDraft(
                name="Capitalized software",
                description="Investment in the logistics platform.",
                description_citations=[
                    Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="continued investment in capitalized software for our logistics platform")
                ],
                amount=AmountMetricDraft(value=None, citations=[]),
            )
        ],
        confidence=0.85,
    )
    verifier = SpendVerifierOutput(agrees=True, confidence=0.85, notes="")

    llm = fake_llm({"SpendExtractionDraft": [draft], "SpendVerifierOutput": [verifier]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company_spend(SpendTopic.CAPEX, company, registry=registry, llm=llm, settings=_settings(tmp_path))
    assert len(result.record.categories) == 1
    assert result.record.categories[0].grounded is True
    assert result.record.needs_review is False
