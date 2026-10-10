from fastapi.testclient import TestClient

from arp.api.deps import get_run_store
from arp.api.main import app
from arp.checks.plausibility import check_less_or_equal, check_part_of_whole, check_sum_to_target
from arp.presets.eu_taxonomy import build_eu_taxonomy_schema
from arp.presets.green import green_summary
from arp.presets.registry import PRESETS
from arp.schemas.common import RunManifest
from arp.schemas.datapoints import ExtractionRecord, FieldStatus
from arp.storage.run_store import RunStore
from tests.test_checks_plausibility import _field, _run

KPIS = ("turnover", "capex", "opex")
OBJ = ("ccm", "cca", "wtr", "ce", "ppc", "bio")


def _spec(fid):
    return next(f for f in build_eu_taxonomy_schema().fields if f.field_id == fid)


def _p(fid, v, period="2024-12-31"):
    return _field(fid, v, unit="%", period=period)


def test_schema_ids_and_drafts():
    schema = build_eu_taxonomy_schema()
    assert schema.schema_id == "sch_eu_taxonomy" and PRESETS["sch_eu_taxonomy"] is build_eu_taxonomy_schema
    by_id = {f.field_id: f for f in schema.fields}
    expected = []
    for k in KPIS:
        a = f"eut_{k}_aligned_pct"
        expected += [a, f"eut_{k}_eligible_not_aligned_pct", f"eut_{k}_not_eligible_pct",
                     *(f"eut_{k}_aligned_{o}_pct" for o in OBJ), f"eut_{k}_enabling_pct", f"eut_{k}_transitional_pct",
                     f"eut_{k}_total_amount"]
        ne = by_id[f"eut_{k}_not_eligible_pct"].check_config
        assert ne.sum_of == [a, f"eut_{k}_eligible_not_aligned_pct"] and ne.sum_target == 100
        assert all(by_id[f"eut_{k}_aligned_{o}_pct"].check_config.part_of == a for o in OBJ)
        assert all(by_id[f"eut_{k}_{x}_pct"].check_config.le_of == [a] for x in ("enabling", "transitional"))
        assert by_id[f"eut_{k}_total_amount"].data_type == "currency_amount"
        assert f"eut_{k}_aligned_by_objective_total" not in by_id
    assert [f.field_id for f in schema.fields][:len(expected)] == expected
    assert by_id["eut_nuclear_gas_reported"].allowed_values == ["yes", "no", "not_disclosed"]
    assert "eut_reporting_year" in by_id
    assert all(f.status == FieldStatus.DRAFT and not f.required for f in schema.fields)
    assert "Article 8" in by_id["eut_turnover_aligned_pct"].extraction_instructions
    assert "ISO 4217" in by_id["eut_capex_total_amount"].extraction_instructions


def _shares(not_eligible):
    spec = _spec("eut_turnover_not_eligible_pct")
    others = [_p("eut_turnover_aligned_pct", 40), _p("eut_turnover_eligible_not_aligned_pct", 35)]
    return _run(check_sum_to_target, spec, _p(spec.field_id, not_eligible), others)


def test_shares_sum_to_100_check():
    assert _shares(25).outcome == "pass"
    r = _shares(30)
    assert (r.check_id, r.outcome) == ("sum_target", "fail")


def test_aligned_le_eligible_relation():
    spec = _spec("eut_capex_enabling_pct")
    aligned = _p("eut_capex_aligned_pct", 20)
    assert _run(check_less_or_equal, spec, _p(spec.field_id, 10), [aligned]).outcome == "pass"
    assert _run(check_less_or_equal, spec, _p(spec.field_id, 25), [aligned]).outcome == "fail"
    obj = _spec("eut_capex_aligned_ccm_pct")
    assert _run(check_part_of_whole, obj, _p(obj.field_id, 25), [aligned]).outcome == "fail"


def _f(field_id, value, period="2024-12-31", unit="EUR"):
    return {"field_id": field_id, "value": value, "canonical_value": value, "canonical_unit": unit, "period_end": period}


def test_green_summary_uses_eu_taxonomy_when_missing():
    green = [_f("green_revenue_total", 100)]
    eut = [_f("eut_turnover_aligned_pct", 30, unit="%"), _f("eut_turnover_total_amount", 200)]
    (r,) = green_summary(green, eut)
    assert (r.aligned, r.beyond_taxonomy, r.flag) == (60, 40, None)
    # the green run's own value wins; another period never matches, a currency mismatch is flagged
    (r,) = green_summary(green + [_f("green_revenue_eu_aligned", 50)], eut)
    assert (r.aligned, r.beyond_taxonomy) == (50, 50)
    (r,) = green_summary(green, [_f("eut_turnover_aligned_pct", 30, unit="%"), _f("eut_turnover_total_amount", 200, period="2023-12-31")])
    assert r.aligned is None
    (r,) = green_summary(green, [_f("eut_turnover_aligned_pct", 30, unit="%"), _f("eut_turnover_total_amount", 200, unit="USD")])
    assert r.beyond_taxonomy is None and r.flag == "unit_mismatch"
    assert green_summary(green)[0].aligned is None


def test_green_summary_endpoint_with_eu_taxonomy_run(tmp_path):
    store = RunStore(tmp_path / "runs")
    for rid, schema_id, fields in [
        ("g1", "sch_green_lowcarbon", [_f("green_revenue_total", 100)]),
        ("e1", "sch_eu_taxonomy", [_f("eut_turnover_aligned_pct", 30, unit="%"), _f("eut_turnover_total_amount", 200)]),
    ]:
        store.save_manifest(RunManifest(run_id=rid, run_type="extraction"))
        rec = ExtractionRecord(company_id="c1", name="Acme", schema_id=schema_id, run_id=rid)
        store.append_jsonl(store._results_path(rid), rec.model_dump(mode="json") | {"fields": fields})
    app.dependency_overrides[get_run_store] = lambda: store
    try:
        c = TestClient(app)
        got = c.get("/api/extraction/runs/g1/green-summary", params={"eu_taxonomy_run_id": "e1"}).json()
        plain = c.get("/api/extraction/runs/g1/green-summary").json()
        assert c.get("/api/extraction/runs/g1/green-summary", params={"eu_taxonomy_run_id": "nope"}).status_code == 404
    finally:
        app.dependency_overrides.pop(get_run_store, None)
    assert (got["rows"][0]["aligned"], got["rows"][0]["beyond_taxonomy"]) == (60, 40)
    assert plain["rows"][0]["aligned"] is None
