from __future__ import annotations

import pytest

from arp.config import Settings
from arp.golden_set import precision
from arp.golden_set.precision import run_precision
from arp.golden_set.schema import ExpectedValue, RecordGoldenCase
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import (
    DataPointSchema,
    ExtractedField,
    ExtractionRecord,
    FieldDataType,
    FieldDefinition,
    RouteKind,
    ValueState,
)

COMPANY = CompanyRef(company_id="acme", name="Acme")


def _row(field_id, value, route, *, state=ValueState.FOUND, canonical=None):
    return ExtractedField(
        field_id=field_id, field_name=field_id, value=value, confidence=0.9, value_state=state,
        canonical_value=canonical, route=route,
    )


@pytest.fixture
def harness(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(precision, "content_store_for", lambda settings: None)  # needs Postgres otherwise

    async def identity(company, **kwargs):
        seen["prepared_with"] = kwargs
        return company

    monkeypatch.setattr(precision, "prepare_company", identity)
    monkeypatch.setattr("arp.orchestration.jobs._xbrl_source", lambda settings: "xbrl")  # Settings() enables XBRL facts

    async def run(rows, expected):
        async def fake_extract(company, schema, **kwargs):
            seen["schema"], seen["kwargs"] = schema, kwargs
            record = ExtractionRecord(company_id=company.company_id, name=company.name, schema_id=schema.schema_id, run_id="r", fields=rows)
            return type("Result", (), {"record": record})()

        monkeypatch.setattr(precision, "_extract_company", fake_extract)
        schema = DataPointSchema(
            name="s", fields=[FieldDefinition(field_id=e.field_id, name=e.field_id, description="d", extraction_instructions="x", data_type=FieldDataType.NUMBER) for e in expected]
        )
        case = RecordGoldenCase(case_id="c1", company=COMPANY, expected=expected)
        report = await run_precision([case], schema=schema, documents_dir=tmp_path, llm=None, verifier_llm=None, settings=Settings())
        return report, seen

    return run


@pytest.mark.asyncio
async def test_precision_review_rate_and_coverage(harness):
    rows = [
        _row("a", 100.0, RouteKind.AUTO_ACCEPT),
        _row("b", 5.0, RouteKind.AUTO_ACCEPT),
        _row("c", 9.0, RouteKind.AUTO_ACCEPT),
        _row("d", 1.0, RouteKind.REVIEW),
    ]
    expected = [
        ExpectedValue(field_id="a", value=100.0, value_state=ValueState.FOUND),
        ExpectedValue(field_id="b", value=5.0, value_state=ValueState.FOUND),
        ExpectedValue(field_id="c", value=10.0, value_state=ValueState.FOUND),  # wrong
        ExpectedValue(field_id="d", value=1.0, value_state=ValueState.FOUND),
    ]
    report, seen = await harness(rows, expected)
    assert (report.total, report.auto_accepted, report.auto_accepted_correct) == (4, 3, 2)
    assert report.precision == pytest.approx(2 / 3)
    assert report.review_rate == 0.25
    assert report.coverage == 0.75
    assert [w["field_id"] for w in report.wrong_auto_accepted] == ["c"]
    assert report.wrong_auto_accepted[0]["case_id"] == "c1"
    # routes as if released and audited
    assert all(f.status.value == "released" for f in seen["schema"].fields)
    assert seen["kwargs"]["qualities"][("a", 1)].first_audit_passed
    assert seen["kwargs"]["trial"] is False
    assert "history" not in seen["kwargs"]
    assert seen["kwargs"]["identifier_map"] is not None
    assert seen["kwargs"]["xbrl_source"] == "xbrl"
    assert seen["prepared_with"]["parent_run"][1] == "golden-precision"


@pytest.mark.asyncio
async def test_not_found_matches_not_found_and_numbers_use_relative_tolerance(harness):
    rows = [
        _row("a", None, RouteKind.AUTO_ACCEPT, state=ValueState.NOT_FOUND),
        _row("b", 1000.0, RouteKind.AUTO_ACCEPT, canonical=1004.0),  # within 0.5% of canonical
        _row("c", 1006.0, RouteKind.AUTO_ACCEPT, canonical=1006000.0),  # outside, raw and canonical
    ]
    expected = [
        ExpectedValue(field_id="a", value_state=ValueState.NOT_FOUND),
        ExpectedValue(field_id="b", value=1000.0, value_state=ValueState.FOUND),
        ExpectedValue(field_id="c", value=1000.0, value_state=ValueState.FOUND),
    ]
    report, _ = await harness(rows, expected)
    assert report.auto_accepted_correct == 2
    assert [w["field_id"] for w in report.wrong_auto_accepted] == ["c"]
    # reports the canonical value and the raw one
    wrong = report.wrong_auto_accepted[0]
    assert (wrong["expected"], wrong["actual"], wrong["actual_raw"]) == (1000.0, 1006000.0, 1006.0)


@pytest.mark.asyncio
async def test_expected_value_matches_raw_or_canonical(harness):
    rows = [
        _row("raw", 1234.0, RouteKind.AUTO_ACCEPT, canonical=1.234e9),  # "EUR 1,234 million", labelled as printed
        _row("canon", 1234.0, RouteKind.AUTO_ACCEPT, canonical=1.234e9),
        _row("near", 1234.0, RouteKind.AUTO_ACCEPT, canonical=1.234e9),
        _row("off", 1234.0, RouteKind.AUTO_ACCEPT, canonical=1.234e9),
    ]
    expected = [
        ExpectedValue(field_id="raw", value=1234.0, value_state=ValueState.FOUND),
        ExpectedValue(field_id="canon", value=1.234e9, value_state=ValueState.FOUND),
        ExpectedValue(field_id="near", value=1238.0, value_state=ValueState.FOUND),  # within 0.5% of the raw value
        ExpectedValue(field_id="off", value=1250.0, value_state=ValueState.FOUND),
    ]
    report, _ = await harness(rows, expected)
    assert [w["field_id"] for w in report.wrong_auto_accepted] == ["off"]
    assert report.auto_accepted_correct == 3


@pytest.mark.asyncio
async def test_no_auto_accepted_rows_gives_no_precision(harness):
    report, _ = await harness(
        [_row("a", 1.0, RouteKind.REVIEW)], [ExpectedValue(field_id="a", value=1.0, value_state=ValueState.FOUND)]
    )
    assert report.precision is None
    assert report.review_rate == 1.0


def _cli_args(monkeypatch, tmp_path, report):
    from arp.cli import golden_set as cli

    async def fake_run(cases, **kwargs):
        return report

    monkeypatch.setattr(cli, "run_precision", fake_run)
    monkeypatch.setattr(cli, "build_llm_client", lambda s: None)
    monkeypatch.setattr(cli, "build_verifier_llm_client", lambda s: None)
    cases = tmp_path / "cases.json"
    cases.write_text("[]")
    schema_id = next(iter(cli.PRESETS))
    return cli, ["precision", "--schema", schema_id, "--cases", str(cases), "--documents-dir", str(tmp_path)]


def test_cli_exits_non_zero_below_min_precision(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from arp.golden_set.schema import PrecisionReport

    report = PrecisionReport(schema_id="s", total=2, auto_accepted=2, auto_accepted_correct=1, precision=0.5, review_rate=0.0, coverage=1.0)
    cli, args = _cli_args(monkeypatch, tmp_path, report)
    assert CliRunner().invoke(cli.golden_set_app, [*args, "--min-precision", "0.97"]).exit_code == 1
    assert CliRunner().invoke(cli.golden_set_app, [*args, "--min-precision", "0.4"]).exit_code == 0


def test_cli_fails_when_nothing_was_auto_accepted(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from arp.golden_set.schema import PrecisionReport

    report = PrecisionReport(schema_id="s", total=2, auto_accepted=0, auto_accepted_correct=0, precision=None, review_rate=1.0, coverage=0.0)
    cli, args = _cli_args(monkeypatch, tmp_path, report)
    result = CliRunner().invoke(cli.golden_set_app, [*args, "--min-precision", "0.0"])
    assert result.exit_code == 1
    assert "no value was auto-accepted" in result.output


def test_found_expected_value_needs_a_value():
    with pytest.raises(ValueError, match="needs a value"):
        ExpectedValue(field_id="a", value_state=ValueState.FOUND)
    ExpectedValue(field_id="a", value_state=ValueState.NOT_FOUND)
