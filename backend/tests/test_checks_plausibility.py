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
