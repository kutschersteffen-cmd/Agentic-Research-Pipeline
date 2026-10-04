from fastapi.testclient import TestClient

from arp.api.deps import get_run_store
from arp.api.main import app
from arp.checks.plausibility import check_part_of_whole, check_sum_identity, check_sum_to_target
from arp.extraction.extractor_agent import ExtractionDraft, PeriodValue
from arp.extraction.pipeline import create_extraction_run, execute_extraction_run
from arp.extraction.verifier_agent import VerifierOutput
from arp.ingestion.registry import DocumentSourceRegistry
from arp.normalise.tables_manifest import TABLES, check_manifest, table_versions
from arp.normalise.value import typed_value
from arp.presets.green import GREEN_TABLE, build_green_schema, green_summary, load_green_categories
from arp.presets.registry import PRESETS, install_preset
from arp.schemas.common import CompanyRef, DocType, RunManifest, SourceDocument
from arp.schemas.datapoints import ExtractionRecord, FieldStatus
from arp.storage.run_store import RunStore
from arp.storage.schema_registry import SchemaRegistry
from tests.test_checks_plausibility import _field, _run
from tests.test_extraction_pipeline import _UNSETTLED, _FixedDocSource, _settings

METRICS = ("revenue", "capex", "opex")
GREEN_IDS = [
    "renewable_energy", "energy_efficiency", "clean_transport", "green_buildings", "grids_storage",
    "hydrogen", "ccus", "low_carbon_materials", "circular_economy", "water_pollution",
]


def test_table_in_manifest():
    assert check_manifest(TABLES, {GREEN_TABLE: table_versions()[GREEN_TABLE]}) == []
    cats = load_green_categories()
    assert [c.category_id for c in cats if c.kind == "green"] == GREEN_IDS
    assert [c.category_id for c in cats if c.kind == "transition"] == ["transition"]
    assert len(cats) == 11 and all(c.include and c.exclude and c.description and c.eu_objective for c in cats)


def test_schema_generated_from_table():
    schema = build_green_schema()
    assert schema.schema_id == "sch_green_lowcarbon" and PRESETS["sch_green_lowcarbon"] is build_green_schema
    by_id = {f.field_id: f for f in schema.fields}
    expected = []
    for m in METRICS:
        cats = [f"green_{m}_{c}" for c in GREEN_IDS]
        status = [f"green_{m}_eu_aligned", f"green_{m}_eu_eligible_not_aligned", f"green_{m}_eu_not_covered"]
        expected += [f"{m}_total", f"green_{m}_total", f"green_{m}_share_pct", f"transition_{m}_total", *cats, *status,
                     f"green_{m}_framework", f"green_{m}_definition"]
        total = by_id[f"green_{m}_total"].check_config
        assert total.sum_of == cats and total.part_of == f"{m}_total" and total.le_of == []
        nc = by_id[f"green_{m}_eu_not_covered"].check_config
        assert nc.sum_of == status[:2] and nc.sum_target_field == f"green_{m}_total"
        assert by_id[f"transition_{m}_total"].check_config.part_of == f"{m}_total"
        assert by_id[f"{m}_total"].check_config.non_negative
        assert all(by_id[f].check_config.part_of == f"green_{m}_total" for f in cats + status)
        assert by_id[f"green_{m}_framework"].allowed_values == [
            "own_definition", "eu_taxonomy", "icma_gbp", "climate_bonds", "china_catalogue", "other"]
    assert [f.field_id for f in schema.fields] == expected
    assert all(f.status == FieldStatus.DRAFT and not f.required for f in schema.fields)
    assert all(GREEN_TABLE in f.extraction_instructions for f in schema.fields)
    cats = {c.category_id: c for c in load_green_categories()}
    for m in METRICS:
        for cid in GREEN_IDS:
            text = by_id[f"green_{m}_{cid}"].extraction_instructions
            assert cats[cid].include in text and cats[cid].exclude in text
        t = by_id[f"transition_{m}_total"].extraction_instructions
        assert cats["transition"].include in t and cats["transition"].exclude in t
        for fid in (f"green_{m}_total", f"green_{m}_eu_aligned", f"green_{m}_eu_not_covered"):
            assert all(cats[c].exclude in by_id[fid].extraction_instructions for c in GREEN_IDS)
        assert cats["hydrogen"].exclude not in by_id[f"green_{m}_framework"].extraction_instructions
    assert "ISO 4217" in by_id["green_revenue_total"].extraction_instructions


def _f(field_id, value, period="2024-12-31", unit="EUR"):
    return {"field_id": field_id, "value": value, "canonical_value": value, "canonical_unit": unit, "period_end": period}


def test_green_summary_beyond_taxonomy():
    rows = green_summary([_f("revenue_total", 500), _f("green_revenue_total", 100), _f("green_revenue_eu_aligned", 40)])
    (r,) = rows
    assert (r.metric, r.period_end, r.green_total, r.aligned, r.beyond_taxonomy, r.flag) == (
        "revenue", "2024-12-31", 100, 40, 60, None)
    assert r.share == 20


def test_aligned_exceeding_green_flagged_not_clipped():
    (r,) = green_summary([_f("green_capex_total", 30), _f("green_capex_eu_aligned", 40)])
    assert r.beyond_taxonomy == -10 and r.flag == "aligned_exceeds_green"


def test_green_summary_missing_and_per_period():
    rows = green_summary([_f("green_opex_total", 10), _f("green_opex_total", 8, period="2023-12-31"),
                          _f("green_opex_share_pct", 4, unit="%")])
    assert [(r.period_end, r.beyond_taxonomy, r.share) for r in rows] == [("2023-12-31", None, None), ("2024-12-31", None, 4)]
    (r,) = green_summary([_f("green_revenue_total", 100), _f("green_revenue_eu_aligned", 40, unit="USD")])
    assert r.beyond_taxonomy is None and r.flag == "unit_mismatch"
    raw = {"field_id": "green_revenue_eu_aligned", "value": 40, "canonical_value": None, "canonical_unit": None,
           "period_end": "2024-12-31"}
    (r,) = green_summary([_f("green_revenue_total", 100), raw])
    assert r.aligned is None and r.beyond_taxonomy is None


def _typed(unit_text, value):
    spec = next(f for f in build_green_schema().fields if f.field_id == "green_revenue_total")
    pv = PeriodValue(value=value, raw_value_text=f"{value}", unit_text=unit_text, period_text="FY2024")
    return typed_value(spec, pv, fiscal_year_end="12-31")


def test_currency_symbol_and_iso_code_share_canonical_unit():
    part, whole = _typed("€ million", 40), _typed("EUR million", 100)
    assert part.canonical_unit == whole.canonical_unit == "EUR" and part.canonical_value == 40_000_000
    spec = next(f for f in build_green_schema().fields if f.field_id == "green_revenue_renewable_energy")
    r = _run(check_part_of_whole, spec, _field(spec.field_id, part.canonical_value, unit=part.canonical_unit),
             [_field("green_revenue_total", whole.canonical_value, unit=whole.canonical_unit)])
    assert r.outcome == "pass"


def _split(not_covered):
    spec = next(f for f in build_green_schema().fields if f.field_id == "green_revenue_eu_not_covered")
    others = [_field("green_revenue_eu_aligned", 40, unit="EUR"), _field("green_revenue_eu_eligible_not_aligned", 30, unit="EUR"),
              _field("green_revenue_total", 100, unit="EUR")]
    field = _field(spec.field_id, not_covered, unit="EUR")
    return _run(check_sum_to_target, spec, field, others), _run(check_sum_identity, spec, field, others)


def test_eu_split_must_equal_green_total():
    target, identity = _split(20)
    assert (target.check_id, target.outcome) == ("sum_target", "fail") and identity.outcome == "not_applicable"
    assert _split(30)[0].outcome == "pass"


async def test_install_and_trial_run_smoke(tmp_path, fake_llm):
    settings = _settings(tmp_path)
    schema = install_preset("sch_green_lowcarbon", SchemaRegistry(settings.schema_registry_dir))
    doc = SourceDocument(
        company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="ESG",
        full_text="Acme Corp report. In fiscal 2024 revenue from renewable energy was EUR 120 million; green capex "
                  "on grids and storage was EUR 40 million. Total revenue was EUR 900 million.",
    )
    n = 3 * len(schema.fields)
    llm = fake_llm({"ExtractionDraft": [ExtractionDraft(values=[], confidence=0.9)] * n,
                    "VerifierOutput": [VerifierOutput(agrees=True, confidence=0.9, notes="ok")] * n,
                    "AdjudicatorOutput": [_UNSETTLED] * n})
    store = RunStore(settings.runs_dir)
    company = CompanyRef(company_id="c1", name="Acme Corp", ticker="ACME")
    run_id = create_extraction_run(schema, [company], settings, store, trial=True)
    await execute_extraction_run(run_id, schema, [company], llm=llm, settings=settings, run_store=store,
                                 registry=DocumentSourceRegistry([_FixedDocSource([doc])]))
    assert store.load_manifest(run_id).status == "completed"
    (row,) = store.read_jsonl(store.results_path(run_id))
    assert {f["field_id"] for f in row["fields"]} == {f.field_id for f in schema.fields}


def test_green_summary_endpoint(tmp_path):
    store = RunStore(tmp_path / "runs")
    schema = build_green_schema()
    run_id = "ext1"
    store.save_manifest(RunManifest(run_id=run_id, run_type="extraction"))
    rec = ExtractionRecord(company_id="c1", name="Acme", schema_id=schema.schema_id, run_id=run_id)
    row = rec.model_dump(mode="json") | {"fields": [_f("green_revenue_total", 100), _f("green_revenue_eu_aligned", 40)]}
    store.append_jsonl(store.results_path(run_id), row)
    app.dependency_overrides[get_run_store] = lambda: store
    try:
        client = TestClient(app)
        got = client.get(f"/api/extraction/runs/{run_id}/green-summary").json()
        assert client.get("/api/extraction/runs/nope/green-summary").status_code == 404
    finally:
        app.dependency_overrides.pop(get_run_store, None)
    assert got["rows"] == [{"company_id": "c1", "name": "Acme", "metric": "revenue", "period_end": "2024-12-31",
                            "unit": "EUR", "green_total": 100, "aligned": 40, "share": None, "beyond_taxonomy": 60,
                            "flag": None}]
