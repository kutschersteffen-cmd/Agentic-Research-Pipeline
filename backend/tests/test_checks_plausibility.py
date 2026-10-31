from arp.checks.plausibility import (
    check_part_of_whole,
    check_percentage,
    check_range,
    check_sign,
    check_sum_identity,
    numeric_of,
)
from arp.checks.runner import CheckContext
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import (
    CheckConfig,
    DataPointSchema,
    ExtractedField,
    FieldDataType,
    FieldDefinition,
)


def _spec(fid, dt=FieldDataType.NUMBER, **cfg):
    return FieldDefinition(
        field_id=fid, name=fid, description="d", data_type=dt, extraction_instructions="i",
        check_config=CheckConfig(**cfg),
    )


def _field(fid, v, unit="tCO2e", period="2024-12-31"):
    return ExtractedField(
        field_id=fid, field_name=fid, value=v, confidence=0.9, value_state="found",
        canonical_value=v, canonical_unit=unit, period_end=period,
    )


def _run(check, spec, field, others=(), specs=()):
    ctx = CheckContext(
        company=CompanyRef(company_id="c1", name="A"), issuer_key="k",
        schema=DataPointSchema(name="s", fields=[spec, *specs]), documents_by_id={},
        record_fields=[field, *others],
    )
    (r,) = check(spec, field, ctx)
    return r


def _tri(a, b, total, **over):
    specs = {
        "s1": _spec("s1", part_of="total"),
        "s2": _spec("s2"),
        "total": _spec("total", sum_of=["s1", "s2"]),
    }
    fields = {"s1": _field("s1", a), "s2": _field("s2", b), "total": _field("total", total)}
    for k, f in over.items():
        fields[k] = f
    return specs, fields


def test_total_below_parts_fails():
    specs, f = _tri(100, 50, 120)
    r = _run(check_sum_identity, specs["total"], f["total"], [f["s1"], f["s2"]])
    assert (r.check_id, r.outcome, r.severity) == ("plausibility.sum_identity", "fail", "warn")
    assert r.detail == "total 120 vs parts 100+50=150"
    assert r.threshold_ref == "total:v1:check_config.sum_tolerance"


def test_total_equal_parts_passes():
    specs, f = _tri(100, 50.5, 150.5)
    assert _run(check_sum_identity, specs["total"], f["total"], [f["s1"], f["s2"]]).outcome == "pass"


def test_part_above_whole_fails():
    specs, f = _tri(200, 50, 150)
    r = _run(check_part_of_whole, specs["s1"], f["s1"], [f["total"]])
    assert (r.check_id, r.outcome, r.severity) == ("plausibility.part_of_whole", "fail", "warn")


def test_percentage_above_100_blocks():
    spec = _spec("p", FieldDataType.PERCENTAGE)
    r = _run(check_percentage, spec, _field("p", 120))
    assert (r.check_id, r.outcome, r.severity) == ("plausibility.percentage", "fail", "block")
    assert r.threshold_ref == "builtin:percentage_0_100"


def test_negative_when_non_negative_blocks():
    spec = _spec("n", non_negative=True)
    r = _run(check_sign, spec, _field("n", -1))
    assert (r.check_id, r.outcome, r.severity) == ("plausibility.sign", "fail", "block")


def test_range_uses_registry_threshold():
    spec = _spec("rng", max_value=1e9)
    r = _run(check_range, spec, _field("rng", 2e9))
    assert r.outcome == "fail" and r.threshold_ref == f"{spec.field_id}:v1:check_config.max_value"


def test_range_not_applicable_without_bounds_or_number():
    assert _run(check_range, _spec("a"), _field("a", 5)).outcome == "not_applicable"
    f = ExtractedField(field_id="a", field_name="a", value="x", confidence=0.5)
    assert _run(check_range, _spec("a", max_value=1), f).outcome == "not_applicable"
    assert numeric_of(f) is None


def test_identity_mismatched_units_not_applicable():
    specs, f = _tri(100, 50, 120, s1=_field("s1", 100, unit="MWh"))
    r = _run(check_sum_identity, specs["total"], f["total"], [f["s1"], f["s2"]])
    assert r.outcome == "not_applicable"


def test_other_period_not_compared():
    specs, f = _tri(100, 50, 120, s1=_field("s1", 100, period="2023-12-31"), s2=_field("s2", 50, period="2023-12-31"))
    r = _run(check_sum_identity, specs["total"], f["total"], [f["s1"], f["s2"]])
    assert r.outcome == "not_applicable"


def test_part_of_whole_mismatched_units_not_applicable():
    specs, f = _tri(200, 50, 150)
    f["total"] = _field("total", 150, unit="MWh")
    assert _run(check_part_of_whole, specs["s1"], f["s1"], [f["total"]]).outcome == "not_applicable"


def test_percentage_boundaries_and_zero_sign_pass():
    spec = _spec("p", FieldDataType.PERCENTAGE)
    assert [_run(check_percentage, spec, _field("p", v)).outcome for v in (0, 100)] == ["pass", "pass"]
    assert _run(check_sign, _spec("n", non_negative=True), _field("n", 0)).outcome == "pass"


# Spec 2026-10-31-extraction-quick-wins, AC-11 to AC-14b
from arp.checks.plausibility import check_ratio  # noqa: E402
from arp.presets.green import build_green_schema  # noqa: E402

_SHARE = _spec("share", FieldDataType.PERCENTAGE, ratio_of=["green", "total"])


def _share(v, green=396.0, total=1000.0, green_unit="EUR", green_period="2024-12-31"):
    others = [_field("total", total, unit="EUR")]
    if green is not None:
        others.append(_field("green", green, unit=green_unit, period=green_period))
    return _run(check_ratio, _SHARE, _field("share", v, unit="%"), others)


def test_ac11_share_fits():
    assert _share(39.6).outcome == "pass"


def test_ac12_share_off():
    r = _share(94.0)
    assert (r.outcome, r.severity, r.detail) == ("fail", "warn", "share 94 vs 396/1000 = 39.6 %")


def test_ac12b_one_point_passes():
    assert _share(40.6).outcome == "pass"


def test_ac12c_beyond_one_point_fails():
    assert _share(40.7).outcome == "fail"


def test_ac13_numerator_other_period():
    assert _share(39.6, green_period="2023-12-31").outcome == "not_applicable"


def test_ac13b_units_differ():
    assert _share(39.6, green_unit="USD").outcome == "not_applicable"


def test_ac13c_zero_denominator():
    assert _share(39.6, total=0.0).outcome == "not_applicable"


def test_ac13d_numerator_not_numeric():
    others = [_field("total", 1000.0, unit="EUR"),
              ExtractedField(field_id="green", field_name="green", value="n/a", confidence=0.9, value_state="found",
                             canonical_unit="EUR", period_end="2024-12-31")]
    assert _run(check_ratio, _SHARE, _field("share", 39.6, unit="%"), others).outcome == "not_applicable"


def test_ratio_negative_denominator_no_crash():
    assert _share(39.6, total=-1000.0).outcome == "fail"


def test_ac14_green_preset_ratio_of():
    fields = {f.field_id: f for f in build_green_schema().fields}
    for m in ("capex", "revenue", "opex"):
        assert fields[f"green_{m}_share_pct"].check_config.ratio_of == [f"green_{m}_total", f"{m}_total"]


def test_ac14b_only_share_fields_bumped():
    for f in build_green_schema().fields:
        assert f.version == (3 if f.field_id.endswith("_share_pct") else 2) + 1, f.field_id  # +1: table routing (2026-10-31)
