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


@pytest.mark.asyncio
async def test_not_found_matches_not_found_and_numbers_use_relative_tolerance(harness):
    rows = [
        _row("a", None, RouteKind.AUTO_ACCEPT, state=ValueState.NOT_FOUND),
        _row("b", 1000.0, RouteKind.AUTO_ACCEPT, canonical=1004.0),  # within 0.5% of canonical
        _row("c", 1000.0, RouteKind.AUTO_ACCEPT, canonical=1006.0),  # outside
    ]
    expected = [
        ExpectedValue(field_id="a", value_state=ValueState.NOT_FOUND),
        ExpectedValue(field_id="b", value=1000.0, value_state=ValueState.FOUND),
        ExpectedValue(field_id="c", value=1000.0, value_state=ValueState.FOUND),
    ]
    report, _ = await harness(rows, expected)
    assert report.auto_accepted_correct == 2
    assert [w["field_id"] for w in report.wrong_auto_accepted] == ["c"]


@pytest.mark.asyncio
async def test_no_auto_accepted_rows_gives_no_precision(harness):
    report, _ = await harness(
        [_row("a", 1.0, RouteKind.REVIEW)], [ExpectedValue(field_id="a", value=1.0, value_state=ValueState.FOUND)]
    )
    assert report.precision is None
    assert report.review_rate == 1.0


def test_cli_exits_non_zero_below_min_precision(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from arp.cli import golden_set as cli
    from arp.golden_set.schema import PrecisionReport

    async def fake_run(cases, **kwargs):
        return PrecisionReport(schema_id="s", total=2, auto_accepted=2, auto_accepted_correct=1, precision=0.5, review_rate=0.0, coverage=1.0)

    monkeypatch.setattr(cli, "run_precision", fake_run)
    monkeypatch.setattr(cli, "build_llm_client", lambda s: None)
    monkeypatch.setattr(cli, "build_verifier_llm_client", lambda s: None)
    cases = tmp_path / "cases.json"
    cases.write_text("[]")
    schema_id = next(iter(cli.PRESETS))
    args = ["precision", "--schema", schema_id, "--cases", str(cases), "--documents-dir", str(tmp_path)]
    assert CliRunner().invoke(cli.golden_set_app, [*args, "--min-precision", "0.97"]).exit_code == 1
    assert CliRunner().invoke(cli.golden_set_app, [*args, "--min-precision", "0.4"]).exit_code == 0
