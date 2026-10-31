"""Transition-plan number rules (spec 2026-10-18-transition-plan-number-rules-design, AC-1..AC-19)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import settings_dep
from arp.api.routers import extraction as extraction_router
from arp.checks.runner import CheckContext, check_record
from arp.config import Settings
from arp.db.fields import SchemaRegistry
from arp.extraction.routing import route
from arp.presets.transition_plan import REQUIRES_YES, SCHEMA_ID, build_transition_plan_schema
from arp.schemas.common import Citation, CompanyRef, DocType, PeriodPlan, SourceDocument
from arp.schemas.datapoints import DataPointSchema, ExtractedField, FieldDefinition, FieldQuality

_SNAPSHOT = json.loads((Path(__file__).parent / "fixtures" / "transition_plan_questions_snapshot.json").read_text())
_HELPERS = [  # field_id, name, data_type, unit, seed_keywords
    ("tp_h_target_pct", "Absolute target reduction", "percentage", "%",
     ["absolute target", "reduction target", "GHG reduction", "emissions reduction", "% reduction", "2030 target"]),
    ("tp_h_target_year", "Absolute target year", "number", None,
     ["target year", "by 2030", "2030", "reduction target", "baseline"]),
    ("tp_h_scope1_emissions", "Scope 1 emissions", "number", "tCO2e",
     ["scope 1", "direct emissions", "GHG emissions", "tCO2e", "emissions table"]),
    ("tp_h_scope2_emissions", "Scope 2 emissions", "number", "tCO2e",
     ["scope 2", "indirect emissions", "market-based", "location-based", "tCO2e"]),
    ("tp_h_scope3_emissions", "Scope 3 emissions", "number", "tCO2e",
     ["scope 3", "value chain emissions", "indirect emissions", "tCO2e"]),
    ("tp_h_scope1_intensity", "Scope 1 intensity", "number", None,
     ["emission intensity", "scope 1 intensity", "tCO2e per", "intensity"]),
    ("tp_h_scope2_intensity", "Scope 2 intensity", "number", None,
     ["emission intensity", "scope 2 intensity", "tCO2e per", "intensity"]),
    ("tp_h_scope3_intensity", "Scope 3 intensity", "number", None,
     ["emission intensity", "scope 3 intensity", "tCO2e per", "intensity"]),
]
_RULES = {  # field_id -> (rule_id, kind, parameters)
    "tp_a_ambition_5": ("tp_r_ambition_5", "threshold", {"conditions": [
        {"field": "tp_h_target_pct", "op": ">=", "value": 50.0},
        {"field": "tp_h_target_year", "op": "<=", "value": 2030.0}]}),
    **{f"tp_a_progress_{q}": (f"tp_r_progress_{q}", "series",
                              {"field": f"tp_h_scope{s}_emissions", "years": 5, "trend": "none"})
       for q, s in ((67, 1), (68, 2), (69, 3))},
    **{f"tp_a_progress_{q}": (f"tp_r_progress_{q}", "series",
                              {"field": f"tp_h_scope{s}_intensity", "years": 5, "trend": "down"})
       for q, s in ((70, 1), (71, 2), (72, 3))},
}


def _fields():
    return {f.field_id: f for f in build_transition_plan_schema().fields}


# --- preset shape ---

def test_helpers_follow_the_64_questions():  # AC-1
    fields = build_transition_plan_schema().fields
    assert len(fields) == 72
    assert [f.field_id for f in fields[:64]] == [s["field_id"] for s in _SNAPSHOT]
    got = [(f.field_id, f.name, f.data_type.value, f.unit, f.seed_keywords) for f in fields[64:]]
    assert got == [tuple(h) for h in _HELPERS]


def test_helpers_are_optional_and_not_high_risk():  # AC-2
    assert all(not f.required and not f.high_risk for f in build_transition_plan_schema().fields[64:])


def test_seven_questions_carry_their_rule():  # AC-3
    fields = _fields()
    for fid, (rule_id, kind, params) in _RULES.items():
        rules = fields[fid].rules
        assert len(rules) == (2 if fid in REQUIRES_YES else 1), fid  # the requires rule comes after (contradiction rules)
        dumped = rules[0].model_dump(mode="json")
        assert (dumped["rule_id"], dumped["kind"], dumped["when"]) == (rule_id, kind, True), fid
        assert {k: dumped[k] for k in params} == params, fid


def test_no_other_field_has_rules():  # AC-16
    assert all(not f.rules for fid, f in _fields().items() if fid not in _RULES and fid not in REQUIRES_YES)


def test_versions():  # AC-4
    fields = _fields()
    for s in _SNAPSHOT:
        want = (2 if s["field_id"] in _RULES else s["version"]) + (s["field_id"] in REQUIRES_YES)  # +1 for the requires rule
        want += 1  # section-tag routing (spec 2026-10-31-table-aware-extraction)
        assert fields[s["field_id"]].version == want, s["field_id"]
    assert all(fields[h[0]].version == 1 for h in _HELPERS)


def test_question_fields_match_main():  # AC-14
    fields = build_transition_plan_schema().fields[:64]
    keys = [k for k in _SNAPSHOT[0] if k != "version"]
    assert [{k: f.model_dump(mode="json")[k] for k in keys} for f in fields] == [
        {k: s[k] for k in keys} for s in _SNAPSHOT
    ]


# --- saving ---

@pytest.fixture
def client(tmp_path, pg):
    settings = Settings(
        anthropic_api_key="x", runs_dir=tmp_path / "runs",
        documents_dir=tmp_path / "docs", cache_dir=tmp_path / "cache", discovery_state_dir=tmp_path / "disc",
    )
    app = FastAPI()
    app.include_router(extraction_router.router)

    @app.exception_handler(ValueError)
    async def _ve(request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u", name="U", role="analyst")
    return TestClient(app)


def _post(client, schema: DataPointSchema):
    return client.post("/api/extraction/schemas", json=schema.model_dump(mode="json"))


def _main_preset() -> DataPointSchema:
    """The preset as it was on main: the 64 question fields, no helpers, no rules."""
    return DataPointSchema(schema_id=SCHEMA_ID, name="Transition plan indicators",
                           fields=[FieldDefinition(**s) for s in _SNAPSHOT])


def test_preset_saves(client):  # AC-5
    assert _post(client, build_transition_plan_schema()).status_code == 200


def _release_main(pg):
    reg = SchemaRegistry(pg)
    s = reg.save(_main_preset())
    reg.release(s.schema_id, s.version)


def test_saves_over_a_released_main_preset(client, pg):  # AC-18
    _release_main(pg)
    r = _post(client, build_transition_plan_schema())
    assert r.status_code == 200, r.text


def test_unbumped_rule_field_is_refused(client, pg):  # AC-19
    _release_main(pg)
    s = build_transition_plan_schema()
    s = s.model_copy(update={"fields": [
        f.model_copy(update={"version": 1}) if f.field_id == "tp_a_progress_67" else f for f in s.fields
    ]})
    r = _post(client, s)
    assert r.status_code == 400 and "changing it needs" in r.text, r.text


# --- rule behaviour ---

_DOC = SourceDocument(
    doc_id="d1", company_id="c1", doc_type=DocType.SUSTAINABILITY_REPORT, title="Report 2024", full_text="x",
    period_plan=PeriodPlan(current="2024-12-31", comparatives=[f"{y}-12-31" for y in (2023, 2022, 2021, 2020)]),
)


def _row(fid, v, period=None, unit=None):
    numeric = isinstance(v, (int, float)) and not isinstance(v, bool)
    return ExtractedField(
        field_id=fid, field_name=fid, value=v, confidence=0.95, value_state="found", grounded=True,
        canonical_value=v if numeric else None, canonical_unit=unit, period_end=period, raw_value_text=str(v),
        citations=[Citation(doc_id="d1", doc_type=DocType.SUSTAINABILITY_REPORT, quote=str(v), span_text=str(v),
                            grounded=True, page=31)],
    )


def _series(fid, values: dict[int, float], unit):
    return [_row(fid, v, f"{y}-12-31", unit) for y, v in values.items()]


def _released() -> DataPointSchema:
    s = build_transition_plan_schema()
    return s.model_copy(update={"fields": [f.model_copy(update={"status": "released"}) for f in s.fields]})


async def _check(rows):
    schema = _released()
    ctx = CheckContext(company=CompanyRef(company_id="c1", name="A"), issuer_key="k", schema=schema,
                       documents_by_id={"d1": _DOC}, record_fields=rows)
    return await check_record(schema, rows, ctx)


def _outcome(rows, fid, rule_id):
    (row,) = [r for r in rows if r.field_id == fid]
    (res,) = [c for c in row.checks if c.check_id == f"rule.{rule_id}"]
    return res.outcome


def _ambition(pct=42, year=2030):
    return [_row("tp_a_ambition_5", True), _row("tp_h_target_pct", pct, unit="%"), _row("tp_h_target_year", year)]


async def test_ambition_42_pct_fails():  # AC-6
    assert _outcome(await _check(_ambition()), "tp_a_ambition_5", "tp_r_ambition_5") == "fail"


async def test_ambition_42_pct_goes_to_review():  # AC-17
    rows = await _check(_ambition())
    (row,) = [r for r in rows if r.field_id == "tp_a_ambition_5"]
    spec = next(f for f in _released().fields if f.field_id == "tp_a_ambition_5")
    r = route(row, FieldQuality(field_id=spec.field_id, version=spec.version, first_audit_passed=True), spec)
    assert r.kind == "review" and "check:rule.tp_r_ambition_5" in r.reasons


async def test_ambition_55_pct_passes():  # AC-7
    assert _outcome(await _check(_ambition(pct=55)), "tp_a_ambition_5", "tp_r_ambition_5") == "pass"


async def test_ambition_2035_fails():  # AC-8
    assert _outcome(await _check(_ambition(pct=55, year=2035)), "tp_a_ambition_5", "tp_r_ambition_5") == "fail"


_FIVE = {2020: 100.0, 2021: 98.0, 2022: 95.0, 2023: 90.0, 2024: 85.0}


async def test_five_years_of_scope_1_pass():  # AC-9
    rows = [_row("tp_a_progress_67", True), *_series("tp_h_scope1_emissions", _FIVE, "tCO2e")]
    assert _outcome(await _check(rows), "tp_a_progress_67", "tp_r_progress_67") == "pass"


async def test_missing_year_of_scope_1_fails():  # AC-10
    four = {y: v for y, v in _FIVE.items() if y != 2022}
    rows = [_row("tp_a_progress_67", True), *_series("tp_h_scope1_emissions", four, "tCO2e")]
    assert _outcome(await _check(rows), "tp_a_progress_67", "tp_r_progress_67") == "fail"


async def test_falling_intensity_passes():  # AC-11
    rows = [_row("tp_a_progress_70", True), *_series("tp_h_scope1_intensity", _FIVE, "tCO2e/EURm")]
    assert _outcome(await _check(rows), "tp_a_progress_70", "tp_r_progress_70") == "pass"


async def test_rising_intensity_fails():  # AC-12
    rising = {**_FIVE, 2024: 120.0}
    rows = [_row("tp_a_progress_70", True), *_series("tp_h_scope1_intensity", rising, "tCO2e/EURm")]
    assert _outcome(await _check(rows), "tp_a_progress_70", "tp_r_progress_70") == "fail"


async def test_no_answer_is_not_checked():  # AC-13
    rows = [_row("tp_a_progress_70", False), *_series("tp_h_scope1_intensity", _FIVE, "tCO2e/EURm")]
    assert _outcome(await _check(rows), "tp_a_progress_70", "tp_r_progress_70") == "not_applicable"


def test_branch_preset_saves_over_main_release(client, pg):
    """This branch's preset (with the requires rules) saves over main's released 72-field preset."""
    main = json.loads((Path(__file__).parent / "fixtures" / "transition_plan_preset_main.json").read_text())
    reg = SchemaRegistry(pg)
    saved = reg.save(DataPointSchema(schema_id=SCHEMA_ID, name="Transition plan indicators",
                                     fields=[FieldDefinition(**f) for f in main]))
    reg.release(saved.schema_id, saved.version)
    r = _post(client, build_transition_plan_schema())
    assert r.status_code == 200, r.text
