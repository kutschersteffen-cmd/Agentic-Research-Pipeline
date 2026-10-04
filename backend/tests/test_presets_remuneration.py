from fastapi.testclient import TestClient

from arp.api.deps import get_run_store
from arp.api.main import app
from arp.presets.registry import PRESETS
from arp.presets.remuneration import build_remuneration_schema, remuneration_summary
from arp.schemas.common import DocType, RunManifest
from arp.schemas.datapoints import ExtractionRecord
from arp.storage.run_store import RunStore
from tests.test_checks_plausibility import _field, _run


def _f(fid, v, unit=None):
    return {"field_id": fid, "value": v, "canonical_value": v if isinstance(v, (int, float)) else None,
            "canonical_unit": unit, "period_end": "2024-12-31"}


def _one(*fields, plan="lti"):
    return next(r for r in remuneration_summary(list(fields)) if r.plan == plan)


def _w(mech, w, *extra):
    return [_f("rem_ceo_lti_mechanism", mech), _f("rem_ceo_lti_esg_weight_pct", w, "%"), *extra]


def test_weighted_15_is_10_or_above():
    r = _one(*_w("weighted", 15))
    assert (r.effective_weight_pct, r.threshold_class) == (15, "10_or_above")


def test_weighted_exactly_10_is_10_or_above():
    assert _one(*_w("weighted", 10.0)).threshold_class == "10_or_above"


def test_weighted_8_is_below_10():
    assert _one(*_w("weighted", 8)).threshold_class == "below_10"


def test_multiplier_09_to_115_effective_15():
    r = _one(_f("rem_ceo_sti_mechanism", "multiplier"), _f("rem_ceo_sti_multiplier_min", 0.9), _f("rem_ceo_sti_multiplier_max", 1.15), plan="sti")
    assert (r.effective_weight_pct, r.threshold_class, r.multiplier_range) == (15, "10_or_above", (0.9, 1.15))


def test_multiplier_095_105_effective_5_below_10():
    r = _one(_f("rem_ceo_lti_mechanism", "multiplier"), _f("rem_ceo_lti_multiplier_min", 0.95), _f("rem_ceo_lti_multiplier_max", 1.05))
    assert (r.effective_weight_pct, r.threshold_class) == (5, "below_10")


def test_underpin_or_discretion_has_no_weight():
    for mech in ("underpin", "discretion"):
        r = _one(_f("rem_ceo_lti_mechanism", mech))
        assert (r.effective_weight_pct, r.threshold_class) == (None, None)


def test_weighted_plus_multiplier_note():
    r = _one(*_w("weighted", 20, _f("rem_ceo_lti_has_multiplier_also", "yes")))
    assert r.effective_weight_pct == 20 and "also has an ESG multiplier" in r.notes and r.also_multiplier == "yes"


def test_climate_weight_le_esg_weight_check():
    from arp.checks.plausibility import check_less_or_equal
    by = {f.field_id: f for f in build_remuneration_schema().fields}
    spec, esg = by["rem_ceo_lti_climate_weight_pct"], by["rem_ceo_lti_esg_weight_pct"]
    assert spec.check_config.le_of == ["rem_ceo_lti_esg_weight_pct"] and spec.unit == "%"
    assert _run(check_less_or_equal, spec, _field("rem_ceo_lti_climate_weight_pct", 12, "%"),
                [_field("rem_ceo_lti_esg_weight_pct", 10, "%")], [esg]).outcome == "fail"
    assert _run(check_less_or_equal, spec, _field("rem_ceo_lti_climate_weight_pct", 5, "%"),
                [_field("rem_ceo_lti_esg_weight_pct", 10, "%")], [esg]).outcome == "pass"
    lo = by["rem_ceo_lti_multiplier_min"]
    assert lo.check_config.le_of == ["rem_ceo_lti_multiplier_max"] and (lo.check_config.min_value, lo.check_config.max_value) == (0, 3)
    assert _run(check_less_or_equal, lo, _field("rem_ceo_lti_multiplier_min", 1.2, None),
                [_field("rem_ceo_lti_multiplier_max", 1.1, None)], [by["rem_ceo_lti_multiplier_max"]]).outcome == "fail"


def test_schema_ids_and_routing():
    schema = build_remuneration_schema()
    assert schema.schema_id == "sch_esg_remuneration" and PRESETS["sch_esg_remuneration"] is build_remuneration_schema
    ids = [f.field_id for f in schema.fields]
    assert len(ids) == len(set(ids)) == 1 + 2 * 2 * 11
    by = {f.field_id: f for f in schema.fields}
    assert "rem_scope" not in by and by["rem_esg_in_pay"].allowed_values == ["yes", "no", "not_disclosed"]
    assert "never copy the CEO" in by["rem_exco_lti_esg_weight_pct"].extraction_instructions
    assert "never copy the CEO" not in by["rem_ceo_lti_esg_weight_pct"].extraction_instructions
    assert by["rem_exco_sti_climate_weight_pct"].check_config.le_of == ["rem_exco_sti_esg_weight_pct"]
    assert by["rem_exco_sti_multiplier_min"].check_config.le_of == ["rem_exco_sti_multiplier_max"]
    assert by["rem_ceo_lti_mechanism"].allowed_values == ["weighted", "multiplier", "underpin", "discretion", "none"]
    assert by["rem_ceo_sti_has_multiplier_also"].allowed_values == ["yes", "no"]
    assert all(not f.required and f.document_routing.doc_types[0] == DocType.PROXY_DEF14A for f in schema.fields)
    assert DocType.ANNUAL_REPORT_10K in by["rem_esg_in_pay"].document_routing.doc_types


def test_remuneration_summary_endpoint(tmp_path):
    store = RunStore(tmp_path / "runs")
    store.save_manifest(RunManifest(run_id="r1", run_type="extraction"))
    rec = ExtractionRecord(company_id="c1", name="Acme", schema_id="sch_esg_remuneration", run_id="r1")
    store.append_jsonl(store.results_path("r1"), rec.model_dump(mode="json") | {"fields": _w("weighted", 12, _f("rem_esg_in_pay", "yes"))})
    app.dependency_overrides[get_run_store] = lambda: store
    try:
        client = TestClient(app)
        got = client.get("/api/extraction/runs/r1/remuneration-summary").json()
        assert client.get("/api/extraction/runs/nope/remuneration-summary").status_code == 404
    finally:
        app.dependency_overrides.pop(get_run_store, None)
    (row,) = got["rows"]
    assert (row["company_id"], row["plan"], row["scope"], row["effective_weight_pct"], row["threshold_class"]) == (
        "c1", "lti", "ceo", 12, "10_or_above")
    assert row["esg_in_pay"] == "yes"


def test_multiplier_boundaries():
    for lo, hi, eff, cls in [(0.9, 1.0, 10, "10_or_above"), (1.0, 1.1, 10, "10_or_above"),
                             (0.9, 1.1, 10, "10_or_above"), (0.91, 1.09, 9, "below_10")]:
        r = _one(_f("rem_ceo_lti_mechanism", "multiplier"), _f("rem_ceo_lti_multiplier_min", lo), _f("rem_ceo_lti_multiplier_max", hi))
        assert (r.effective_weight_pct, r.threshold_class) == (eff, cls), (lo, hi)


def test_ceo_and_exco_rows_are_separate_and_pay_falls_back():
    pay = {**_f("rem_esg_in_pay", "yes"), "period_end": "2023-12-31"}
    rows = remuneration_summary([pay, _f("rem_ceo_sti_esg_weight_pct", 5, "%"), _f("rem_exco_sti_esg_weight_pct", 12, "%")])
    assert [(r.scope, r.plan, r.weight_pct, r.esg_in_pay) for r in rows] == [
        ("ceo", "sti", 5, "yes"), ("executive_committee", "sti", 12, "yes")]
