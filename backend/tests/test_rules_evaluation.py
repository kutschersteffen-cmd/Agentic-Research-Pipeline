"""Rule evaluation in check_record (schema-rules spec, AC-1..AC-20, AC-64, AC-72, AC-74, AC-75)."""
from __future__ import annotations

from arp.checks.runner import CheckContext, check_record
from arp.extraction.routing import route
from arp.schemas.common import Citation, CompanyRef, DocType, PeriodPlan, SourceDocument
from arp.schemas.datapoints import DataPointSchema, ExtractedField, FieldQuality
from arp.schemas.rules import Condition, RequiresRule, ThresholdRule
from tests.rules_fixtures import R1, R2, R3, R4, R5, R6, schema_f, with_rules

_UNITS = {f.field_id: f.unit for f in schema_f().fields}
_DOC = SourceDocument(
    doc_id="d1", company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="Report 2024", full_text="x",
    period_plan=PeriodPlan(current="2024-12-31", comparatives=[f"{y}-12-31" for y in (2023, 2022, 2021, 2020)]),
)


def _row(fid, v, period=None, *, state="found", grounded=True, unit="default"):
    numeric = isinstance(v, (int, float)) and not isinstance(v, bool)
    return ExtractedField(
        field_id=fid, field_name=fid, value=v, confidence=0.95, value_state=state, grounded=grounded,
        canonical_value=v if numeric else None, canonical_unit=_UNITS[fid] if unit == "default" else unit,
        period_end=period, raw_value_text=str(v),
        citations=[Citation(doc_id="d1", doc_type=DocType.SUSTAINABILITY_REPORT, quote=str(v), span_text=str(v), grounded=True, page=31)],
    )


def _schema(rules: dict) -> DataPointSchema:
    s = with_rules(schema_f(), rules)
    return s.model_copy(update={"fields": [f.model_copy(update={"status": "released"}) for f in s.fields]})


async def _run(rules: dict, rows: list[ExtractedField], docs=(_DOC,)) -> list[ExtractedField]:
    schema = _schema(rules)
    ctx = CheckContext(
        company=CompanyRef(company_id="c1", name="A"), issuer_key="k", schema=schema,
        documents_by_id={d.doc_id: d for d in docs}, record_fields=rows,
    )
    return await check_record(schema, rows, ctx)


def _rule(row: ExtractedField, rule_id: str):
    return [r for r in row.checks if r.check_id == f"rule.{rule_id}"]


def _only(rows, fid, rule_id):
    (row,) = [r for r in rows if r.field_id == fid]
    (res,) = _rule(row, rule_id)
    return row, res


def _route(rows, fid):
    schema = _schema({})
    (row,) = [r for r in rows if r.field_id == fid]
    (spec,) = [f for f in schema.fields if f.field_id == fid]
    return route(row, FieldQuality(field_id=fid, version=1, first_audit_passed=True), spec)


def _r1_rows(**over):
    rows = {"ambition": _row("ambition", True), "pct": _row("pct", 42), "year": _row("year", 2030)}
    rows.update(over)
    return [r for r in rows.values() if r is not None]


R1_SENTENCE = "When Halving target is YES: needs Target reduction >= 50 and Target year <= 2030."


# --- threshold (R1) ---

async def test_r1_fails():  # AC-1
    _, res = _only(await _run({"ambition": [R1()]}, _r1_rows()), "ambition", "R1")
    assert (res.outcome, res.severity, res.layer) == ("fail", "warn", 3)
    assert res.threshold_ref == "ambition:v1:rules.R1"


async def test_r1_fail_routes_to_review():  # AC-2
    r = _route(await _run({"ambition": [R1()]}, _r1_rows()), "ambition")
    assert r.kind == "review"
    assert "check:rule.R1" in r.reasons


async def test_r1_detail_exact():  # AC-3
    _, res = _only(await _run({"ambition": [R1()]}, _r1_rows()), "ambition", "R1")
    assert res.detail == f"{R1_SENTENCE} Failed. Found Target reduction = 42 (p. 31), Target year = 2030 (p. 31)."


async def test_rule_leaves_value_alone():  # AC-4
    rows = _r1_rows()
    row, _ = _only(await _run({"ambition": [R1()]}, rows), "ambition", "R1")
    src = rows[0]
    assert (row.value, row.value_state, row.confidence, row.citations) == (src.value, src.value_state, src.confidence, src.citations)


async def test_r1_passes():  # AC-5
    _, res = _only(await _run({"ambition": [R1()]}, _r1_rows(pct=_row("pct", 55))), "ambition", "R1")
    assert (res.outcome, res.detail) == ("pass", "")


async def test_r1_pass_adds_no_rule_reason():  # AC-6
    r = _route(await _run({"ambition": [R1()]}, _r1_rows(pct=_row("pct", 55))), "ambition")
    assert not [x for x in r.reasons if x.startswith("check:rule.")]
    assert r.kind == "auto_accept"


async def test_when_mismatch_not_applicable():  # AC-7
    _, res = _only(await _run({"ambition": [R1()]}, _r1_rows(ambition=_row("ambition", False))), "ambition", "R1")
    assert (res.outcome, res.detail) == ("not_applicable", "")


async def test_checked_row_not_found_not_applicable():  # AC-8
    rows = _r1_rows(ambition=_row("ambition", None, state="not_found"))
    _, res = _only(await _run({"ambition": [R1()]}, rows), "ambition", "R1")
    assert res.outcome == "not_applicable"


async def test_missing_input_detail_exact():  # AC-9
    _, res = _only(await _run({"ambition": [R1()]}, _r1_rows(pct=None)), "ambition", "R1")
    assert res.detail == f"{R1_SENTENCE} Failed. Found Target year = 2030 (p. 31). Not found: Target reduction."


async def test_ungrounded_input_not_found():  # AC-10
    _, res = _only(await _run({"ambition": [R1()]}, _r1_rows(pct=_row("pct", 55, grounded=False))), "ambition", "R1")
    assert res.outcome == "fail"
    assert res.detail.endswith("Not found: Target reduction.")


async def test_latest_period_used_for_undated_checked_row():  # AC-11
    rows = [_row("ambition", True), _row("pct", 30, "2023-12-31"), _row("pct", 55, "2024-12-31"), _row("year", 2030)]
    _, res = _only(await _run({"ambition": [R1()]}, rows), "ambition", "R1")
    assert res.outcome == "pass"


async def test_threshold_on_currency_with_unit_passes():  # AC-72
    r10 = ThresholdRule(rule_id="R10", kind="threshold", when=True, conditions=[Condition(field="green", op=">=", value=25)])
    _, res = _only(await _run({"ambition": [r10]}, [_row("ambition", True), _row("green", 30)]), "ambition", "R10")
    assert res.outcome == "pass"


async def test_one_result_per_checked_row():  # AC-74
    rows = [
        _row("ambition", True, "2023-12-31"), _row("ambition", True, "2024-12-31"),
        _row("pct", 55, "2023-12-31"), _row("pct", 42, "2024-12-31"), _row("year", 2030),
    ]
    out = {r.period_end: _rule(r, "R1") for r in await _run({"ambition": [R1()]}, rows) if r.field_id == "ambition"}
    assert [x.outcome for x in out["2023-12-31"]] == ["pass"]
    assert [x.outcome for x in out["2024-12-31"]] == ["fail"]


async def test_no_matching_period_is_not_found():  # AC-75
    rows = [_row("ambition", True, "2024-12-31"), _row("pct", 55, "2022-12-31"), _row("pct", 60, "2023-12-31"), _row("year", 2030)]
    _, res = _only(await _run({"ambition": [R1()]}, rows), "ambition", "R1")
    assert res.outcome == "fail"
    assert res.detail.endswith("Not found: Target reduction.")


async def test_rules_run_after_blocking_layer():  # AC-64
    rows = _r1_rows(ambition=_row("ambition", "yes"))
    row, res = _only(await _run({"ambition": [R1()]}, rows), "ambition", "R1")
    assert any(r.check_id == "format.data_type" and r.outcome == "fail" and r.severity == "block" for r in row.checks)
    assert res.check_id == "rule.R1"


async def test_zero_value_counts_as_found():
    _, res = _only(await _run({"ambition": [R1()]}, _r1_rows(pct=_row("pct", 0, state="zero"))), "ambition", "R1")
    assert res.outcome == "fail"
    assert "Found Target reduction = 0 (p. 31)" in res.detail


# --- requires (R2), label (R4) ---

async def test_requires_fails():  # AC-12
    _, res = _only(await _run({"nz2050": [R2()]}, [_row("nz2050", True), _row("nz", False)]), "nz2050", "R2")
    assert res.outcome == "fail"
    assert res.detail == "When Net zero by 2050 is YES: needs Net-zero target to be YES. Failed. Found Net-zero target = NO (p. 31)."


async def test_label_fails():  # AC-17
    _, res = _only(await _run({"s1": [R4()]}, [_row("s1", True), _row("kind", "combined")]), "s1", "R4")
    assert res.outcome == "fail"


async def test_when_on_enum_matches_string():
    rule = RequiresRule(rule_id="R11", kind="requires", when="combined", field="s1", equals=True)
    schema_rules = {"kind": [rule]}
    _, res = _only(await _run(schema_rules, [_row("kind", "combined"), _row("s1", True)]), "kind", "R11")
    assert res.outcome == "pass"
    _, res = _only(await _run(schema_rules, [_row("kind", "standalone"), _row("s1", True)]), "kind", "R11")
    assert res.outcome == "not_applicable"


# --- series (R3) ---

def _int1(values: dict[int, float], **units):
    return [_row("declined", True), *[_row("int1", v, f"{y}-12-31", unit=units.get(str(y), "default")) for y, v in values.items()]]


_SERIES = {2020: 10, 2021: 9.5, 2022: 9, 2023: 8.5, 2024: 8}


async def test_series_passes():  # AC-13
    _, res = _only(await _run({"declined": [R3()]}, _int1(_SERIES)), "declined", "R3")
    assert res.outcome == "pass"


async def test_series_missing_year():  # AC-14
    _, res = _only(await _run({"declined": [R3()]}, _int1({y: v for y, v in _SERIES.items() if y != 2023})), "declined", "R3")
    assert res.outcome == "fail"
    assert "Not found: Scope 1 intensity 2023." in res.detail
    assert res.detail == (
        "When Intensity declined is YES: needs Scope 1 intensity for 5 years up to the report year, falling. Failed. "
        "Found Scope 1 intensity 2020 = 10, 2021 = 9.5, 2022 = 9, 2024 = 8. Not found: Scope 1 intensity 2023."
    )


async def test_series_trend_broken():  # AC-15
    _, res = _only(await _run({"declined": [R3()]}, _int1({**_SERIES, 2024: 11})), "declined", "R3")
    assert res.outcome == "fail"


async def test_series_units_differ():  # AC-16
    _, res = _only(await _run({"declined": [R3()]}, _int1(_SERIES, **{"2022": "tCO2e/USDm"})), "declined", "R3")
    assert res.outcome == "fail"
    assert res.detail.endswith("Units differ.")


async def test_series_duplicate_year_counted_once():
    rows = [*_int1(_SERIES), _row("int1", 12, "2024-12-31")]
    _, res = _only(await _run({"declined": [R3()]}, rows), "declined", "R3")
    assert res.outcome == "pass"


async def test_series_without_report_year():
    _, res = _only(await _run({"declined": [R3()]}, _int1(_SERIES), docs=()), "declined", "R3")
    assert res.outcome == "fail"
    assert res.detail.endswith("Failed. Report year unknown.")


# --- computed (R5, R6) ---

async def test_ratio_detail_exact():  # AC-18
    rows = [_row("green", 30), _row("total", 200), _row("share", 20)]
    _, res = _only(await _run({"share": [R5()]}, rows), "share", "R5")
    assert res.detail == (
        "Green capex share should equal Green capex ÷ Total capex × 100, within 1. Failed. "
        "Found Green capex = 30 (p. 31), Total capex = 200 (p. 31), Green capex share = 20 (p. 31). Expected 15."
    )


async def test_ratio_within_tolerance():  # AC-19
    rows = [_row("green", 30), _row("total", 200), _row("share", 15.4)]
    _, res = _only(await _run({"share": [R5()]}, rows), "share", "R5")
    assert res.outcome == "pass"


async def test_sum_within_tolerance():  # AC-20
    rows = [_row("green", 30), _row("other", 170), _row("total", 200.4)]
    _, res = _only(await _run({"total": [R6()]}, rows), "total", "R6")
    assert res.outcome == "pass"


async def test_ratio_with_zero_denominator():
    rows = [_row("green", 30), _row("total", 0, state="zero"), _row("share", 20)]
    _, res = _only(await _run({"share": [R5()]}, rows), "share", "R5")
    assert res.outcome == "fail"
    assert res.detail.endswith(
        "Failed. Found Green capex = 30 (p. 31), Total capex = 0 (p. 31), Green capex share = 20 (p. 31). Cannot divide by zero."
    )
