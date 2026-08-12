from arp.config import Settings
from arp.extraction.extractor_agent import ExtractionDraft
from arp.extraction.pipeline import _extract_company
from arp.extraction.verifier_agent import VerifierOutput
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition


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


def _schema() -> DataPointSchema:
    field = FieldDefinition(
        name="green_capex_usd_m",
        description="Green capex in USD millions for the most recent fiscal year.",
        data_type=FieldDataType.CURRENCY_AMOUNT,
        unit="USD millions",
        extraction_instructions="Find the disclosed green/sustainable capex figure for the latest fiscal year.",
        seed_keywords=["green capex", "sustainable capital expenditure"],
    )
    return DataPointSchema(name="Green Capex", fields=[field])


async def test_extract_company_grounded_value_not_flagged(tmp_path, fake_llm):
    doc = SourceDocument(
        company_id="c1",
        doc_type=DocType.SUSTAINABILITY_REPORT,
        title="ESG report",
        full_text="In fiscal 2025, we invested $120 million in green capex across our facilities.",
    )
    schema = _schema()
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")

    quote = "invested $120 million in green capex"
    draft = ExtractionDraft(
        value=120.0,
        raw_value_text="$120 million in green capex",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=quote)],
        confidence=0.9,
    )
    verifier = VerifierOutput(agrees=True, corrected_value=None, confidence=0.9, notes="Matches the cited text.")

    llm = fake_llm({"ExtractionDraft": [draft], "VerifierOutput": [verifier]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company(company, schema, registry=registry, llm=llm, settings=_settings(tmp_path))
    field_result = result.record.fields[0]
    assert field_result.value == 120.0
    assert field_result.grounded is True
    assert result.record.needs_review is False


async def test_extract_company_verifier_disagreement_flags_review(tmp_path, fake_llm):
    doc = SourceDocument(
        company_id="c1",
        doc_type=DocType.SUSTAINABILITY_REPORT,
        title="ESG report",
        full_text="In fiscal 2024, we invested $80 million in green capex; fiscal 2025 guidance is $120 million.",
    )
    schema = _schema()
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")

    quote = "invested $80 million in green capex"
    draft = ExtractionDraft(
        value=80.0,
        raw_value_text="$80 million in green capex",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=quote)],
        confidence=0.7,
    )
    # verifier catches that 80M was fiscal 2024, not the most recent year requested
    verifier = VerifierOutput(
        agrees=False, corrected_value=120.0, confidence=0.85, notes="80M was FY2024; instructions require latest FY (2025 guidance = 120M)."
    )

    llm = fake_llm({"ExtractionDraft": [draft], "VerifierOutput": [verifier]})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company(company, schema, registry=registry, llm=llm, settings=_settings(tmp_path))
    field_result = result.record.fields[0]
    assert field_result.value == 120.0  # verifier's correction wins
    assert result.record.needs_review is True


async def test_extract_company_no_evidence_skips_llm_and_not_flagged(tmp_path, fake_llm):
    doc = SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG", full_text="We sell shoes.")
    schema = _schema()
    company = CompanyRef(company_id="c1", name="Shoe Co", ticker="SHOE")

    llm = fake_llm({})
    registry = DocumentSourceRegistry([_FixedDocSource([doc])])

    result = await _extract_company(company, schema, registry=registry, llm=llm, settings=_settings(tmp_path))
    assert result.record.fields[0].value is None
    assert result.record.needs_review is False
    assert llm.calls == []
