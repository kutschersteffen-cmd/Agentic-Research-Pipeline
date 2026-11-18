"""showcase-stewardship-fixes AC-47..AC-51: a file in the company's own folder passes the entity check."""

import pytest

from arp.config import Settings
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.pipeline import _extract_company
from arp.extraction.verifier_agent import VerifierOutput
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.planning.entity_check import confirm_entity
from arp.schemas.common import Citation, CompanyRef, DocType, MatchStatus, SourceDocument
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition

LEI_A, LEI_B = "5493001KJTIIGC8Y1R12", "529900T8BM49AURSDO55"
ACME = CompanyRef(company_id="acme", name="Acme Group plc", lei=LEI_A)
TEXT = "In fiscal 2025, we invested $120 million in green capex."


def upload(**kw):
    return SourceDocument(**{"company_id": "acme", "doc_type": DocType.SUSTAINABILITY_REPORT, "title": "report.txt",
                             "full_text": TEXT, "local_path": "/docs/acme/sustainability_report/report.txt", **kw})


def test_own_folder_file_is_confirmed():  # AC-47
    assert confirm_entity(upload(), ACME).match_status == MatchStatus.CONFIRMED


def test_other_company_folder_stays_ambiguous():  # AC-48 (must not change)
    assert confirm_entity(upload(company_id="other"), ACME).match_status == MatchStatus.AMBIGUOUS


def test_foreign_lei_still_mismatches():  # AC-49 (must not change)
    assert confirm_entity(upload(full_text=f"LEI {LEI_B}\n{TEXT}"), ACME).match_status == MatchStatus.MISMATCH


def test_without_local_path_stays_ambiguous():  # AC-50 (must not change)
    assert confirm_entity(upload(local_path=None), ACME).match_status == MatchStatus.AMBIGUOUS


class _Src(DocumentSource):
    name = "fixed"

    def __init__(self, docs):
        self._docs = docs

    async def fetch(self, company, doc_types=None):
        return self._docs


@pytest.mark.usefixtures("pg")
async def test_extraction_over_own_file_has_no_entity_route(tmp_path, fake_llm):  # AC-51
    doc = upload()
    field = FieldDefinition(name="green_capex_usd_m", description="Green capex in USD millions.",
                            data_type=FieldDataType.CURRENCY_AMOUNT, unit="USD millions",
                            extraction_instructions="Find green capex.", seed_keywords=["green capex"])
    draft = ExtractionDraft(values=[PeriodValue(
        value=120.0, raw_value_text="$120 million in green capex", unit_text="USD million", period_text="fiscal 2025",
        citations=[Citation(doc_id=doc.doc_id, doc_type=doc.doc_type, quote="invested $120 million in green capex")])],
        confidence=0.9)
    llm = fake_llm({"ExtractionDraft": [draft],
                    "VerifierOutput": [VerifierOutput(agrees=True, corrected_value=None, confidence=0.9, notes="ok")]})
    settings = Settings(anthropic_api_key="unused", runs_dir=tmp_path / "r", schema_registry_dir=tmp_path / "s",
                        documents_dir=tmp_path / "d", cache_dir=tmp_path / "c", discovery_state_dir=tmp_path / "x")
    result = await _extract_company(ACME, DataPointSchema(name="Green Capex", fields=[field]),
                                    registry=DocumentSourceRegistry([_Src([doc])]), llm=llm, settings=settings)
    assert result.record.fields
    assert not any("check:consistency.entity" in f.route_reasons for f in result.record.fields)
