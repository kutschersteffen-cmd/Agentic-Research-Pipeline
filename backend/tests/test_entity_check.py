from arp.config import Settings
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.pipeline import _extract_company
from arp.extraction.verifier_agent import VerifierOutput
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.planning.entity_check import confirm_entity
from arp.schemas.common import Citation, CompanyRef, DocType, MatchStatus, SourceDocument
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition

LEI_A = "5493001KJTIIGC8Y1R12"
LEI_B = "529900T8BM49AURSDO55"
ACME = CompanyRef(company_id="c1", name="Acme Group plc")


def _doc(title="Report", text="Nothing here.", **kw):
    return SourceDocument(company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title=title, full_text=text, **kw)


def test_subsidiary_report_holds_parent_passes():
    sub = confirm_entity(_doc("Acme Energy GmbH Sustainability Report 2023"), ACME)
    assert (sub.match_status, sub.covered_entity) == (MatchStatus.MISMATCH, "Acme Energy GmbH")
    assert confirm_entity(_doc("Acme Group plc Annual Report 2023"), ACME).match_status == MatchStatus.CONFIRMED


def test_issuer_lei_in_text_confirms():
    c = ACME.model_copy(update={"lei": LEI_A})
    assert confirm_entity(_doc(text=f"LEI {LEI_A}"), c).match_status == MatchStatus.CONFIRMED


def test_foreign_lei_in_text_mismatches():
    c = ACME.model_copy(update={"lei": LEI_A})
    d = confirm_entity(_doc(text=f"LEI {LEI_B}"), c)
    assert (d.match_status, d.covered_entity) == (MatchStatus.MISMATCH, LEI_B)


def test_provisional_issuer_with_lei_in_text_not_mismatch():
    assert confirm_entity(_doc(text=f"LEI {LEI_B}"), ACME).match_status == MatchStatus.AMBIGUOUS


def test_idmap_supplies_lei(tmp_path):
    from arp.schemas.issuer import IdentifierMap
    from arp.storage.identifier_map import IdentifierMapStore

    store = IdentifierMapStore(tmp_path / "m.jsonl")
    store.add(IdentifierMap(issuer_key=LEI_A, scheme="CIK", value="123"))
    c = ACME.model_copy(update={"cik": "0000123"})
    assert confirm_entity(_doc(text=f"LEI {LEI_B}"), c, store).match_status == MatchStatus.MISMATCH
    assert confirm_entity(_doc(text=f"LEI {LEI_B}"), c, None).match_status == MatchStatus.AMBIGUOUS


def test_auditor_name_in_body_is_ambiguous_not_mismatch():
    d = confirm_entity(_doc(text="KPMG AG\nIndependent auditor's report"), ACME)
    assert d.match_status == MatchStatus.AMBIGUOUS


def test_edgar_doc_by_cik_confirmed():
    c = ACME.model_copy(update={"cik": "0000320193"})
    d = _doc("Something Else Inc 10-K", source_url="https://www.sec.gov/Archives/edgar/data/320193/000/x.htm")
    assert confirm_entity(d, c).match_status == MatchStatus.CONFIRMED


def test_old_source_document_loads_with_no_status():
    d = SourceDocument.model_validate(
        {"company_id": "c1", "doc_type": "10-K", "title": "t", "full_text": "x"}
    )
    assert d.match_status is None and d.covered_entity is None


class _Src(DocumentSource):
    name = "fixed"

    def __init__(self, docs):
        self._docs = docs

    async def fetch(self, company, doc_types=None):
        return self._docs


async def test_held_document_not_extracted(tmp_path, fake_llm):
    sub = _doc("Acme Energy GmbH Sustainability Report 2023", "Acme Energy invested $50 million in green capex.")
    parent = _doc("Acme Group plc Annual Report 2023", "In fiscal 2023, we invested $120 million in green capex.")
    field = FieldDefinition(
        name="green_capex_usd_m",
        description="Green capex in USD millions.",
        data_type=FieldDataType.CURRENCY_AMOUNT,
        unit="USD millions",
        extraction_instructions="Find green capex.",
        seed_keywords=["green capex"],
    )
    schema = DataPointSchema(name="Green Capex", fields=[field])
    draft = ExtractionDraft(
        values=[PeriodValue(
            value=120.0, raw_value_text="$120 million in green capex", unit_text="USD million",
            period_text="fiscal 2023",
            citations=[Citation(doc_id=parent.doc_id, doc_type=parent.doc_type, quote="invested $120 million in green capex")],
        )],
        confidence=0.9,
    )
    llm = fake_llm({
        "ExtractionDraft": [draft],
        "VerifierOutput": [VerifierOutput(agrees=True, corrected_value=None, confidence=0.9, notes="ok")],
    })
    settings = Settings(
        anthropic_api_key="unused", runs_dir=tmp_path / "r", schema_registry_dir=tmp_path / "s",
        documents_dir=tmp_path / "d", cache_dir=tmp_path / "c", discovery_state_dir=tmp_path / "x",
    )
    result = await _extract_company(
        ACME, schema, registry=DocumentSourceRegistry([_Src([sub, parent])]), llm=llm, settings=settings
    )
    assert llm.prompts and all(sub.doc_id not in p for p in llm.prompts)
    assert any(parent.doc_id in p for p in llm.prompts)
    assert result.record.held_documents[0]["doc_id"] == sub.doc_id
