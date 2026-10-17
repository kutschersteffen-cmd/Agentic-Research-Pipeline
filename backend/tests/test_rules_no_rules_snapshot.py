"""AC-59: a schema with no rules checks and routes exactly as on `main` (snapshot captured there)."""
from __future__ import annotations

import json
from pathlib import Path

from arp.checks.runner import CheckContext, check_record
from arp.extraction.routing import route
from arp.schemas.common import Citation, CompanyRef, DocType, PeriodPlan, SourceDocument
from arp.schemas.datapoints import CheckConfig, DataPointSchema, ExtractedField, FieldDefinition, FieldQuality

SNAPSHOT = Path(__file__).parent / "fixtures" / "no_rules_snapshot.json"


def _spec(fid, dt, unit=None, **kw):
    return FieldDefinition(
        field_id=fid, name=fid, description="d", data_type=dt, unit=unit, extraction_instructions="i", status="released", **kw
    )


def _row(fid, v, period=None, *, state="found", unit=None, confidence=0.95, grounded=True):
    numeric = isinstance(v, (int, float)) and not isinstance(v, bool)
    return ExtractedField(
        field_id=fid, field_name=fid, value=v, confidence=confidence, value_state=state, grounded=grounded,
        canonical_value=v if numeric else None, canonical_unit=unit, period_end=period, raw_value_text=None if v is None else str(v),
        citations=[] if v is None else [Citation(doc_id="d1", doc_type="sustainability_report", quote=str(v), span_text=str(v), grounded=True, page=31)],
    )


async def _output() -> list[dict]:
    schema = DataPointSchema(name="snap", fields=[
        _spec("s1", "number", "tCO2e", check_config=CheckConfig(min_value=0, max_value=100)),
        _spec("total", "currency_amount", "EUR millions", check_config=CheckConfig(sum_of=["green", "other"])),
        _spec("green", "currency_amount", "EUR millions", check_config=CheckConfig(part_of="total")),
        _spec("other", "currency_amount", "EUR millions"),
        _spec("share", "percentage"),
        _spec("flag", "boolean", high_risk=True),
        _spec("kind", "enum", allowed_values=["a", "b"]),
    ])
    rows = [
        _row("s1", 120, "2024-12-31", unit="tCO2e"),
        _row("s1", 80, "2023-12-31", unit="tCO2e"),
        _row("total", 200, "2024-12-31", unit="EUR millions"),
        _row("green", 30, "2024-12-31", unit="EUR millions"),
        _row("other", 160, "2024-12-31", unit="EUR millions"),
        _row("share", 140),
        _row("flag", None, state="not_found", confidence=0.5),
        _row("kind", "c", confidence=0.7),
    ]
    doc = SourceDocument(
        doc_id="d1", company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="Report 2024", full_text="x",
        period_plan=PeriodPlan(current="2024-12-31"),
    )
    ctx = CheckContext(
        company=CompanyRef(company_id="c1", name="A"), issuer_key="k", schema=schema,
        documents_by_id={"d1": doc}, record_fields=rows,
    )
    specs = {f.field_id: f for f in schema.fields}
    out = []
    for row in await check_record(schema, rows, ctx):
        r = route(row, FieldQuality(field_id=row.field_id, version=1, first_audit_passed=True), specs[row.field_id])
        out.append({"checks": [c.model_dump(mode="json") for c in row.checks], "route": str(r.kind), "route_reasons": r.reasons})
    return out


async def test_no_rules_output_unchanged():  # AC-59
    assert await _output() == json.loads(SNAPSHOT.read_text(encoding="utf-8"))
