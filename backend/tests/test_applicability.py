from arp.config import Settings
from arp.extraction.pipeline import create_extraction_run, execute_extraction_run
from arp.ingestion.base import DocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.planning.applicability import not_applicable_reason, plan_fields
from arp.schemas.common import CompanyRef, DocType, SourceDocument
from arp.schemas.datapoints import ApplicabilityRules, DataPointSchema, FieldDataType, FieldDefinition
from arp.storage.run_store import RunStore

MANUFACTURING = ApplicabilityRules(sector_codes=[str(n) for n in range(10, 34)])


def _field(name="mfg_only", rules=None, kw="kw"):
    return FieldDefinition(
        name=name, description=name, data_type=FieldDataType.NUMBER, extraction_instructions=name,
        seed_keywords=[kw], applicability_rules=rules,
    )


def _co(**kw):
    return CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME", **kw)


def test_manufacturer_keeps_field():
    f = _field(rules=MANUFACTURING)
    keep, skipped = plan_fields(DataPointSchema(name="s", fields=[f]), _co(isic_code="2410"))
    assert keep == [f] and skipped == []


def test_bank_row_shape():
    f = _field(rules=MANUFACTURING)
    keep, (row,) = plan_fields(DataPointSchema(name="s", fields=[f]), _co(isic_code="6419"))
    assert keep == []
    assert row.value is None and row.value_state == "not_applicable" and row.confidence == 0.0
    assert row.grounded and row.route_reasons == ["not_applicable_by_rule"] and row.review_reasons == []
    assert row.verifier_notes.startswith("isic 6419 not in sector_codes")


def test_country_and_regime_rules():
    f = _field(rules=ApplicabilityRules(countries=["DE"], regimes=["CSRD"]))
    assert not_applicable_reason(f, _co(country="de", regimes=["CSRD", "SEC"])) is None
    assert "country" in not_applicable_reason(f, _co(country="US", regimes=["CSRD"]))
    assert "regimes" in not_applicable_reason(f, _co(country="DE", regimes=["SEC"]))


def test_unknown_company_attributes_never_skip():
    f = _field(rules=ApplicabilityRules(sector_codes=["10"], countries=["DE"], regimes=["CSRD"]))
    assert not_applicable_reason(f, _co(isic_code=None, country=None, regimes=[])) is None


def test_old_field_without_rules_loads():
    f = FieldDefinition.model_validate(
        {"name": "n", "description": "d", "data_type": "number", "extraction_instructions": "x"}
    )
    assert f.applicability_rules is None
    assert not_applicable_reason(f, _co(isic_code="6419")) is None


class _Src(DocumentSource):
    name = "fixed"

    def __init__(self, docs):
        self._docs = docs

    async def fetch(self, company, doc_types=None):
        return self._docs


async def test_bank_skips_manufacturing_only_field(tmp_path, fake_llm):
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG", full_text="Nothing relevant here."
    )
    skipped_f, kept_f = _field("mfg_only", MANUFACTURING, "mfgkw"), _field("general", None, "generalkw")
    schema = DataPointSchema(name="Two", fields=[skipped_f, kept_f])
    company = _co(isic_code="6419")
    llm = fake_llm({})
    settings = Settings(
        anthropic_api_key="unused", runs_dir=tmp_path / "r", schema_registry_dir=tmp_path / "s",
        documents_dir=tmp_path / "d", cache_dir=tmp_path / "c", discovery_state_dir=tmp_path / "x",
    )
    run_store = RunStore(settings.runs_dir)
    run_id = create_extraction_run(schema, [company], settings, run_store, trial=True)
    await execute_extraction_run(
        run_id, schema, [company], llm=llm, registry=DocumentSourceRegistry([_Src([doc])]),
        settings=settings, run_store=run_store,
    )
    assert all("mfg_only" not in p for p in llm.prompts)
    (row,) = run_store.read_jsonl(run_store._results_path(run_id))
    by_id = {f["field_id"]: f for f in row["fields"]}
    skipped = by_id[skipped_f.field_id]
    assert skipped["value_state"] == "not_applicable" and skipped["review_reasons"] == []
    # A trial never auto-accepts, so even the rule skip goes to review.
    assert skipped["route"] == "review" and skipped["route_reasons"] == ["unreleased_version", "not_applicable_by_rule"]
    queued = run_store.read_jsonl(run_store._review_queue_path(run_id))
    assert any(r["field"]["field_id"] == skipped_f.field_id for r in queued)


def test_regimes_and_isic_compare_trimmed_and_case_insensitive():
    assert not_applicable_reason(_field(rules=ApplicabilityRules(regimes=["CSRD"])), _co(regimes=["csrd"])) is None
    assert not_applicable_reason(_field(rules=MANUFACTURING), _co(isic_code=" 2410")) is None
    assert not_applicable_reason(_field(rules=MANUFACTURING), _co(isic_code=" 6419")) is not None
