from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import settings_dep
from arp.api.routers import extraction as extraction_router
from arp.config import Settings
from arp.extraction.schema_builder import RuleSuggestion, RuleSuggestions
from arp.schemas.datapoints import FieldDataType as T
from arp.schemas.datapoints import FieldDefinition
from arp.schemas.rules import ComputedRule, Condition, RequiresRule, ThresholdRule
from tests.rules_fixtures import R1, schema_f, schema_f_with_r1_r6


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
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u", name="U", role="analyst")
    return TestClient(app)


@pytest.fixture
def suggest(client, monkeypatch, fake_llm):
    """suggest(schema, RuleSuggestions) -> response; the model stand-in returns the given output."""
    def _suggest(schema, output: RuleSuggestions):
        llm = fake_llm({"RuleSuggestions": [output]})
        monkeypatch.setattr(extraction_router, "get_llm_client", lambda: llm)
        r = client.post("/api/extraction/schemas/suggest-rules", json=schema.model_dump(mode="json"))
        assert r.status_code == 200, r.text
        return r.json()
    return _suggest


def _f_minus_total():
    s = schema_f()
    return s.model_copy(update={"fields": [f for f in s.fields if f.field_id != "total"]})


def _helper(field_id: str, name: str) -> FieldDefinition:
    return FieldDefinition(
        field_id=field_id, name=name, description=f"{name}.", data_type=T.CURRENCY_AMOUNT,
        unit="EUR millions", extraction_instructions="Find it.",
    )


def _share_ratio(rule_id: str, total_id: str) -> RuleSuggestion:
    return RuleSuggestion(field_id="share", rule=ComputedRule(
        rule_id=rule_id, kind="computed", formula="ratio_pct", inputs=["green", total_id], tolerance=1))


def test_invalid_suggestion_and_its_helper_dropped(suggest):  # AC-35
    ghost = RuleSuggestion(field_id="ambition", rule=ThresholdRule(
        rule_id="g", kind="threshold", conditions=[Condition(field="ghost", op=">=", value=1)]))
    out = suggest(_f_minus_total(), RuleSuggestions(
        rules=[_share_ratio("a", "h_total"), ghost],
        helper_fields=[_helper("h_total", "Total capex"), _helper("h_ghost", "Ghost capex")],
    ))
    assert len(out["rules"]) == 1
    assert [h["name"] for h in out["helper_fields"]] == ["Total capex"]


def test_helpers_merged_by_name(suggest):  # AC-36
    second = RuleSuggestion(field_id="ambition", rule=ThresholdRule(
        rule_id="b", kind="threshold", conditions=[Condition(field="h2", op=">=", value=1)]))
    out = suggest(_f_minus_total(), RuleSuggestions(
        rules=[_share_ratio("a", "h1"), second],
        helper_fields=[_helper("h1", "total capex"), _helper("h2", "Total Capex")],
    ))
    assert len(out["helper_fields"]) == 1
    helper_id = out["helper_fields"][0]["field_id"]
    assert helper_id == "h1"
    assert out["rules"][0]["rule"]["inputs"] == ["green", helper_id]
    assert out["rules"][1]["rule"]["conditions"][0]["field"] == helper_id


def test_helper_merged_into_existing_field(suggest):  # AC-63
    out = suggest(schema_f(), RuleSuggestions(
        rules=[_share_ratio("a", "h_total")], helper_fields=[_helper("h_total", "TOTAL CAPEX")]))
    assert out["helper_fields"] == []
    assert out["rules"][0]["rule"]["inputs"] == ["green", "total"]


def test_suggest_saves_nothing(client, suggest):  # AC-37
    saved = client.post("/api/extraction/schemas", json=schema_f().model_dump(mode="json"))
    assert saved.status_code == 200
    before = client.get("/api/extraction/schemas").json()
    out = suggest(_f_minus_total(), RuleSuggestions(
        rules=[_share_ratio("a", "h_total")], helper_fields=[_helper("h_total", "Total capex")]))
    assert len(out["rules"]) == 1 and len(out["helper_fields"]) == 1
    assert client.get("/api/extraction/schemas").json() == before


def test_suggested_rule_ids_are_fresh(suggest):
    schema = schema_f_with_r1_r6()
    taken = {r.rule_id for f in schema.fields for r in f.rules}
    again = RuleSuggestion(field_id="year", rule=R1().model_copy(update={"conditions": [Condition(field="pct", op=">=", value=1)], "when": None}))
    other = RuleSuggestion(field_id="nz", rule=RequiresRule(rule_id="R1", kind="requires", field="nz2050", equals=True))
    out = suggest(schema, RuleSuggestions(rules=[again, other]))
    ids = [r["rule"]["rule_id"] for r in out["rules"]]
    assert len(ids) == 2 and len(set(ids)) == 2 and not set(ids) & taken


def test_rule_on_unknown_target_dropped(suggest):
    out = suggest(schema_f(), RuleSuggestions(rules=[
        RuleSuggestion(field_id="ghost", rule=RequiresRule(rule_id="a", kind="requires", field="nz", equals=True))]))
    assert out["rules"] == []


def test_prompt_lists_each_field(client, monkeypatch, fake_llm):
    llm = fake_llm({"RuleSuggestions": [RuleSuggestions()]})
    monkeypatch.setattr(extraction_router, "get_llm_client", lambda: llm)
    client.post("/api/extraction/schemas/suggest-rules", json=schema_f().model_dump(mode="json"))
    prompt = llm.prompts[0]
    for needle in ("kind", "Target type", "standalone", "EUR millions", "Find it."):
        assert needle in prompt


def test_helper_reusing_an_existing_field_id_gets_a_new_one(suggest):
    out = suggest(_f_minus_total(), RuleSuggestions(
        rules=[_share_ratio("a", "other")], helper_fields=[_helper("other", "Total capex")]))
    helper_id = out["helper_fields"][0]["field_id"]
    assert helper_id != "other" and out["rules"][0]["rule"]["inputs"] == ["green", helper_id]
