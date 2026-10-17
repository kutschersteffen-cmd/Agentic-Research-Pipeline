from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

from arp.api.auth import Principal, current_user
from arp.api.deps import settings_dep
from arp.api.routers import extraction as extraction_router
from arp.config import Settings
from arp.db import models as m
from arp.db.fields import SchemaRegistry
from arp.db.session import transaction
from arp.schemas.datapoints import DerivedRule
from arp.schemas.rules import ComputedRule, Condition, ThresholdRule
from tests.rules_fixtures import R1, R2, R3, R4, R5, schema_f, schema_f_with_r1_r6, with_rules


@pytest.fixture
def settings(tmp_path, pg):
    return Settings(
        anthropic_api_key="x", runs_dir=tmp_path / "runs",
        documents_dir=tmp_path / "docs", cache_dir=tmp_path / "cache", discovery_state_dir=tmp_path / "disc",
    )


@pytest.fixture
def client(settings):
    app = FastAPI()
    app.include_router(extraction_router.router)

    @app.exception_handler(ValueError)
    async def _ve(request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u", name="U", role="analyst")
    return TestClient(app)


def _post(client, schema):
    return client.post("/api/extraction/schemas", json=schema.model_dump(mode="json"))


def _rejected(client, schema, rule_id):
    r = _post(client, schema)
    # detail[].input echoes the posted schema, so check the messages, not the whole body
    assert r.status_code == 422 and any(f"rule {rule_id}:" in e["msg"] for e in r.json()["detail"]), r.text


def _one(field_id, rule, **overrides):
    return with_rules(schema_f(**overrides), {field_id: [rule]})


def test_unknown_field_rejected(client):  # AC-22
    r1 = R1().model_copy(update={"conditions": [Condition(field="ghost", op=">=", value=50), Condition(field="year", op="<=", value=2030)]})
    _rejected(client, _one("ambition", r1), "R1")


def test_computed_input_is_own_field_rejected(client):  # AC-23
    r5 = R5().model_copy(update={"inputs": ["share", "total"]})
    _rejected(client, _one("share", r5), "R5")


def test_threshold_on_enum_rejected(client):  # AC-24
    r7 = ThresholdRule(rule_id="R7", kind="threshold", conditions=[Condition(field="kind", op=">=", value=1)])
    _rejected(client, _one("ambition", r7), "R7")


def test_threshold_on_unitless_currency_rejected(client):  # AC-25, control AC-69
    r8 = ThresholdRule(rule_id="R8", kind="threshold", conditions=[Condition(field="green", op=">=", value=25)])
    _rejected(client, _one("ambition", r8, green={"unit": None}), "R8")
    assert _post(client, schema_f(green={"unit": None})).status_code == 200


def test_label_on_non_enum_rejected(client):  # AC-26
    _rejected(client, _one("s1", R4().model_copy(update={"field": "pct"})), "R4")


def test_label_value_outside_allowed_rejected(client):  # AC-27
    _rejected(client, _one("s1", R4().model_copy(update={"not_in": ["partial"]})), "R4")


@pytest.mark.parametrize("years", [0, 6])
def test_series_years_out_of_range_rejected(client, years):  # AC-28
    r3 = R3().model_copy(update={"years": years})
    r = client.post("/api/extraction/schemas", json=_one("declined", r3).model_dump(mode="json"))
    assert r.status_code == 422 and any("rule R3:" in e["msg"] for e in r.json()["detail"]), r.text


def test_rule_naming_derived_field_rejected(client):  # AC-29, AC-67, controls AC-70
    # AC-29: nz is derived and R2 names it; AC-67: nz2050 is derived and carries R2
    d29 = {"nz": {"derived_rule": DerivedRule(any_of=["ambition"])}}
    d67 = {"nz2050": {"derived_rule": DerivedRule(any_of=["nz"])}}
    _rejected(client, _one("nz2050", R2(), **d29), "R2")
    _rejected(client, _one("nz2050", R2(), **d67), "R2")
    assert _post(client, schema_f(**d29)).status_code == 200
    assert _post(client, schema_f(**d67)).status_code == 200


def test_duplicate_rule_id_rejected(client):  # AC-30
    s = with_rules(schema_f(), {"ambition": [R1()], "nz2050": [R2().model_copy(update={"rule_id": "R1"})]})
    _rejected(client, s, "R1")


def test_computed_on_non_numeric_own_field_rejected(client):  # AC-68
    r9 = ComputedRule(rule_id="R9", kind="computed", formula="sum", inputs=["green", "other"], tolerance=1)
    _rejected(client, _one("ambition", r9), "R9")


def test_rules_round_trip(client):  # AC-32
    posted = _post(client, schema_f_with_r1_r6())
    assert posted.status_code == 200, posted.text
    fetched = client.get(f"/api/extraction/schemas/{posted.json()['schema_id']}").json()
    want = schema_f_with_r1_r6().model_dump(mode="json")["fields"]
    assert [f["rules"] for f in fetched["fields"]] == [f["rules"] for f in want]
    assert {r["rule_id"] for f in fetched["fields"] for r in f["rules"]} == {"R1", "R2", "R3", "R4", "R5", "R6"}


def test_released_field_gains_rule_refused(client, pg):  # AC-33
    reg = SchemaRegistry(pg)
    s = reg.save(schema_f())
    reg.release(s.schema_id, s.version)
    r = _post(client, with_rules(s, {"ambition": [R1()]}))
    assert r.status_code == 400 and "changing it needs" in r.text, r.text


def test_released_schema_without_rules_resaves_same_versions(client, pg):  # AC-34
    reg = SchemaRegistry(pg)
    s = reg.save(schema_f())
    reg.release(s.schema_id, s.version)
    with transaction(pg) as tx:  # what a schema released before `rules` existed looks like
        row = tx.get(m.DataSchema, (s.schema_id, s.version))
        row.body = {**row.body, "fields": [{k: v for k, v in f.items() if k != "rules"} for f in row.body["fields"]]}
        for fd in tx.query(m.FieldDefinition).all():
            fd.definition = {k: v for k, v in fd.definition.items() if k != "rules"}
    fetched = client.get(f"/api/extraction/schemas/{s.schema_id}").json()
    r = client.post("/api/extraction/schemas", json=fetched)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == s.version
    assert [(f["field_id"], f["version"]) for f in r.json()["fields"]] == [(f.field_id, f.version) for f in s.fields]



@pytest.mark.parametrize(("formula", "inputs", "tolerance", "msg"), [
    ("sum", ["green", "other"], -0.1, "tolerance must not be negative"),
    ("ratio_pct", ["green"], 1, "ratio_pct needs exactly 2 inputs"),
    ("ratio_pct", ["green", "total", "other"], 1, "ratio_pct needs exactly 2 inputs"),
    ("sum", ["green"], 1, "sum needs at least 2 inputs"),
])
def test_computed_shape_rejected(formula, inputs, tolerance, msg):
    with pytest.raises(ValidationError, match=f"rule R9: {msg}"):
        ComputedRule(rule_id="R9", kind="computed", formula=formula, inputs=inputs, tolerance=tolerance)


def test_computed_shape_accepted():
    ComputedRule(rule_id="R9", kind="computed", formula="ratio_pct", inputs=["green", "total"], tolerance=0)
    ComputedRule(rule_id="R9", kind="computed", formula="sum", inputs=["green", "other", "total"])
