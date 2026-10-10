from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import get_run_store
from arp.api.main import app
from arp.checks.prior_period import RestatementCandidate
from arp.orchestration.review_queue import append_decision
from arp.schemas.common import RunManifest
from arp.schemas.datapoints import DataPointSchema, FieldDefinition
from arp.schemas.review import ReviewDecision
from arp.storage.run_store import RunStore

ALICE = Principal(user_id="u_alice", name="Alice Reviewer", role="analyst")
BOB = Principal(user_id="u_bob", name="Bob", role="analyst")
CAROL = Principal(user_id="u_carol", name="Carol", role="approver")
VALUE_KEY = "ISS1:f1:2024-12-31"


@pytest.fixture
def run_store(tmp_path):
    return RunStore(tmp_path / "runs")


def _queue(rs, run_id, row):
    rs.append_jsonl(rs._review_queue_path(run_id), row)


@pytest.fixture
def five_kinds(run_store):
    rs = run_store
    for run_id, run_type in [("ext1", "extraction"), ("idn1", "identity"), ("thm1", "theme"), ("vot1", "voting")]:
        rs.save_manifest(RunManifest(run_id=run_id, run_type=run_type))
    _queue(rs, "ext1", {"item_key": VALUE_KEY, "issuer_key": "ISS1", "company_id": "C1", "field_id": "f1",
                        "period_end": "2024-12-31", "field": {"field_id": "f1", "value": 10}})
    _queue(rs, "ext1", {"item_key": "C2", "company_id": "C2", "name": "Beta", "confidence": 0.0, "rationale": "Identity failed"})
    rs.append_jsonl(rs._results_path("ext1"), {
        "company_id": "C1", "name": "Acme", "issuer_key": "ISS1", "fields": [],
        "held_documents": [{"doc_id": "d1", "title": "Other entity report", "covered_entity": "Acme Sub",
                            "match_status": "mismatch", "content_key": "ck1", "parser_version": "1", "doc_type": "annual_report"}],
    })
    rs.append_jsonl(rs._restatements_path("ext1"), RestatementCandidate(
        candidate_id="rst_1", item_key="ISS1:f1:2023-12-31", issuer_key="ISS1", field_id="f1", period_end="2023-12-31",
        previous_value=9, previous_run_id="ext0", new_value=8, run_id="ext1",
    ).model_dump(mode="json"))
    _queue(rs, "idn1", {"item_key": "C1", "company_id": "C1", "name": "Acme"})
    _queue(rs, "thm1", {"item_key": "isic:C1", "kind": "sector_code", "company_id": "C1", "name": "Acme",
                        "isic_code": "C10", "source": "model"})
    _queue(rs, "thm1", {"item_key": "C1:a1", "activity_id": "a1"})
    _queue(rs, "vot1", {"item_key": "m1"})
    return rs


def _client(rs, who=None):
    app.dependency_overrides[get_run_store] = lambda: rs
    if who is not None:
        app.dependency_overrides[current_user] = lambda: who
    return TestClient(app)


@pytest.fixture(autouse=True)
def _drop_run_store_override():
    yield
    app.dependency_overrides.pop(get_run_store, None)


def _items(rs, who=None, **params):
    r = _client(rs, who).get("/api/review/items", params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _decide(rs, run_id, key, who, decision, reason, second_required=False, value=None):
    append_decision(rs, run_id, ReviewDecision(
        item_key=key, decision=decision, reason_code=reason, reviewer=who.name, user_id=who.user_id, role=who.role,
        corrected_value={"value": value} if value is not None else None, snapshot_id="s1", step="first",
        second_required=second_required,
    ))


def test_all_five_kinds_in_one_list(five_kinds):
    items = _items(five_kinds)
    assert {i["kind"] for i in items} == {"value", "quarantined_document", "restatement_candidate", "identity", "sector_code", "other"}
    assert all(i["state"] == "pending" for i in items)
    held = next(i for i in items if i["kind"] == "quarantined_document")
    assert held["item_key"] == "held:C1:d1" and held["payload"]["issuer_key"] == "ISS1"
    assert next(i for i in items if i["kind"] == "restatement_candidate")["item_key"] == "rst_1"


def test_voting_run_excluded(five_kinds):
    assert all(i["run_type"] != "voting" for i in _items(five_kinds))
    assert _items(five_kinds, run_id="vot1") == []


def test_run_filter(five_kinds):
    items = _items(five_kinds, run_id="idn1")
    assert [(i["kind"], i["item_key"]) for i in items] == [("identity", "C1")]


def test_final_items_not_listed_first_done_listed(five_kinds):
    _decide(five_kinds, "idn1", "C1", CAROL, "approve", "confirmed")
    _decide(five_kinds, "ext1", VALUE_KEY, CAROL, "correct", "wrong_value", second_required=True, value=11)
    items = _items(five_kinds)
    assert not any(i["run_id"] == "idn1" for i in items)
    value = next(i for i in items if i["item_key"] == VALUE_KEY)
    assert value["state"] == "first_done" and value["decision"]["decision"] == "correct"


def test_blind_item_hides_decision_in_list(five_kinds):
    schema = DataPointSchema(name="s", fields=[FieldDefinition(
        field_id="f1", name="Scope 1", description="d", data_type="number", extraction_instructions="x", high_risk=True)])
    (five_kinds.run_dir("ext1") / "schema.json").write_text(schema.model_dump_json())
    _decide(five_kinds, "ext1", VALUE_KEY, ALICE, "correct", "wrong_value", second_required=True, value=11)

    def value_item(who):
        return next(i for i in _items(five_kinds, who, run_id="ext1") if i["item_key"] == VALUE_KEY)

    bob = value_item(BOB)
    assert bob["high_risk"] and bob["state"] == "first_done" and bob["decision"] is None
    assert value_item(ALICE)["decision"]["mine"] is True
    assert value_item(CAROL)["decision"]["decision"] == "correct"


def test_legacy_company_level_row_is_value_item(run_store):
    run_store.save_manifest(RunManifest(run_id="ext9", run_type="extraction"))
    _queue(run_store, "ext9", {"item_key": "C1", "company_id": "C1", "fields": [{"field_id": "f1", "value": 1}]})
    assert [i["kind"] for i in _items(run_store)] == ["value"]


def test_no_user_id_in_items_response(five_kinds):
    _decide(five_kinds, "ext1", VALUE_KEY, ALICE, "correct", "wrong_value", second_required=True, value=11)
    text = _client(five_kinds).get("/api/review/items").text
    assert "user_id" not in text and "Alice Reviewer" not in text


def test_theme_review_route_refuses_isic_keys(five_kinds):
    r = _client(five_kinds).post("/api/themes/runs/thm1/review", json={"item_key": "isic:C1", "decision": "approve"})
    assert r.status_code == 400
    assert r.json()["detail"] == "decide sector codes through the review workbench"
    assert five_kinds.read_jsonl(five_kinds._review_decisions_path("thm1")) == []


def test_theme_review_queue_leaves_out_sector_codes(five_kinds):
    _decide(five_kinds, "thm1", "isic:C1", ALICE, "approve", "confirmed", second_required=True)
    r = _client(five_kinds).get("/api/themes/runs/thm1/review-queue")
    assert r.status_code == 200
    assert [x["item_key"] for x in r.json()["pending"]] == ["C1:a1"] and r.json()["decided"] == []
    assert "u_alice" not in r.text and "Alice Reviewer" not in r.text
