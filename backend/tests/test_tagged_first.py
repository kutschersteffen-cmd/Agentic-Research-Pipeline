"""E29: a field with XBRL tags takes the filer's own tagged value before any model call."""

from arp.config import Settings
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.pipeline import _extract_company
from arp.extraction.verifier_agent import VerifierOutput
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.ingestion.xbrl import XbrlFactSource
from arp.schemas.common import Citation, CompanyRef, DocType, SourceDocument
from arp.schemas.datapoints import (
    DataPointSchema,
    ExtractedField,
    FieldDataType,
    FieldDefinition,
    FieldQuality,
    FieldStatus,
)

_TEXT = "Acme Corp annual report 2024. Total revenues were $383,285 million in fiscal 2024."
_QUOTE = "Total revenues were $383,285 million"


class _Docs(DocumentSource):
    name = "fixed"

    def __init__(self, docs):
        self._docs = docs

    async def fetch(self, company, doc_types=None):
        return self._docs


class _FakeXbrl:
    def __init__(self, facts):
        self._facts = facts
        self.fetches = 0

    async def resolve_cik(self, cik, ticker):
        return cik

    async def fetch_company_facts(self, cik):
        self.fetches += 1
        return self._facts


def _facts(fy: int, end: str) -> dict:
    row = {"start": f"{fy}-01-01", "end": end, "val": 383285000000, "fy": fy, "fp": "FY", "form": "10-K",
           "filed": f"{fy + 1}-02-01", "accn": f"0001-{fy % 100}-000001"}
    return {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [row]}}}}}


def _settings(tmp_path) -> Settings:
    return Settings(
        anthropic_api_key="unused", runs_dir=tmp_path / "runs", schema_registry_dir=tmp_path / "schemas",
        documents_dir=tmp_path / "docs", cache_dir=tmp_path / "cache", discovery_state_dir=tmp_path / "disc",
    )


def _field(tags: list[str]) -> FieldDefinition:
    return FieldDefinition(
        name="revenue_usd_m", description="Total revenue.", data_type=FieldDataType.CURRENCY_AMOUNT, unit="USD millions",
        extraction_instructions="Total revenue for the fiscal year.", seed_keywords=["revenues"], xbrl_tags=tags,
        status=FieldStatus.RELEASED,
    )


def _doc() -> SourceDocument:
    return SourceDocument(company_id="c1", doc_type=DocType.ANNUAL_REPORT_10K, title="Annual report 2024", full_text=_TEXT)


def _llms(fake_llm, doc):
    draft = ExtractionDraft(
        values=[PeriodValue(value=383285.0, raw_value_text="$383,285 million", unit_text="USD million", period_text="fiscal 2024",
                            citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote=_QUOTE)])],
        confidence=0.9,
    )
    verifier = VerifierOutput(agrees=True, corrected_value=None, confidence=0.9, notes="ok")
    return fake_llm({"ExtractionDraft": [draft]}), fake_llm({"VerifierOutput": [verifier]})


async def _run(tmp_path, fake_llm, field, facts, *, qualities=None):
    doc = _doc()
    llm, verifier_llm = _llms(fake_llm, doc)
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME", cik="0000320193")
    result = await _extract_company(
        company, DataPointSchema(name="Rev", fields=[field], release_flag=True), registry=DocumentSourceRegistry([_Docs([doc])]),
        llm=llm, verifier_llm=verifier_llm, settings=_settings(tmp_path), xbrl_source=_FakeXbrl(facts), qualities=qualities,
    )
    return result.record.fields, llm, verifier_llm


async def test_tagged_field_makes_zero_model_calls(tmp_path, fake_llm):
    fields, llm, verifier_llm = await _run(tmp_path, fake_llm, _field(["us-gaap:Revenues"]), _facts(2024, "2024-12-31"))
    (f,) = fields
    assert f.method == "tagged"
    assert "Revenues" in f.citations[0].quote
    assert f.grounded is True and f.confidence == 1.0
    assert (f.value, f.unit) == (383285000000.0, "USD")
    assert (f.canonical_value, f.canonical_unit) == (383285.0, "USD millions")  # the normalise.value path
    assert f.period_end == "2024-12-31"
    assert llm.calls == [] and verifier_llm.calls == []


async def test_fact_for_other_year_falls_through(tmp_path, fake_llm):
    fields, llm, verifier_llm = await _run(tmp_path, fake_llm, _field(["us-gaap:Revenues"]), _facts(2022, "2022-12-31"))
    (f,) = fields
    assert f.method == "extracted"
    assert len(llm.calls) + len(verifier_llm.calls) > 0
    assert f.value == 383285.0


async def test_untagged_field_unchanged(tmp_path, fake_llm):
    fields, llm, verifier_llm = await _run(tmp_path, fake_llm, _field([]), _facts(2024, "2024-12-31"))
    (f,) = fields
    assert f.method == "extracted"
    assert llm.calls == ["ExtractionDraft"] and verifier_llm.calls == ["VerifierOutput"]


async def test_tagged_value_auto_accepts_when_checks_pass(tmp_path, fake_llm):
    field = _field(["us-gaap:Revenues"])
    qualities = {(field.field_id, field.version): FieldQuality(field_id=field.field_id, version=field.version, first_audit_passed=True)}
    fields, _, _ = await _run(tmp_path, fake_llm, field, _facts(2024, "2024-12-31"), qualities=qualities)
    (f,) = fields
    assert f.method == "tagged"
    assert f.route == "auto_accept", f.route_reasons


def test_old_row_without_method_reads_as_extracted():
    row = {"field_id": "f1", "field_name": "x", "value": 1.0, "confidence": 0.9}
    assert ExtractedField.model_validate(row).method == "extracted"


def test_fact_for_tags_annual_full_year_only():
    rows = [
        # A quarter inside the 10-K (fp FY, form 10-K) and a 10-Q: neither is the annual figure.
        {"start": "2024-10-01", "end": "2024-12-31", "val": 1, "fy": 2024, "fp": "FY", "form": "10-K", "filed": "2025-02-01"},
        {"start": "2024-01-01", "end": "2024-12-31", "val": 2, "fy": 2025, "fp": "Q1", "form": "10-Q", "filed": "2025-05-01"},
        {"start": "2024-01-01", "end": "2024-12-31", "val": 3, "fy": 2024, "fp": "FY", "form": "10-K", "filed": "2025-02-01"},
    ]
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": rows}}}}}
    assert XbrlFactSource.fact_for_tags(facts, ["us-gaap:Missing", "us-gaap:Revenues"], fiscal_year=2024).value == 3
    assert XbrlFactSource.fact_for_tags(facts, ["us-gaap:Revenues"], fiscal_year=2023) is None
