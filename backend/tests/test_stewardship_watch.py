"""Watch list, PR 1 (spec stewardship-commitment-loop): schema, proof statements, watch topics, objective
results and the suggestion confirm/reject API. Suggestions are written straight to the table here; the
check that writes them is PR 2."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from typer.testing import CliRunner

from arp.api.auth import current_user
from arp.api.deps import get_engagement_store, settings_dep
from arp.api.main import app
from arp.cli import app as cli
from arp.config import Settings, get_settings
from arp.db.session import transaction
from arp.schemas.common import new_id
from arp.schemas.engagement import Commitment, CorrespondenceEntry, Objective
from arp.storage.engagement_store import EngagementStore
from arp.storage.postgres import get_engine
from arp.storage.postgres_engagement_store import PostgresEngagementStore
from arp.storage.postgres_models import STEWARDSHIP_TABLES, WATCH_TABLES, StwEvidenceSuggestionModel
from tests.conftest import PRINCIPAL

URL = "/api/stewardship"
PROOF = "The 2026 annual report names a board climate committee"
Q = "The board formed a climate committee in March 2026."


@pytest.fixture
def client(pg, monkeypatch, tmp_path):
    monkeypatch.setenv("ARP_ENGAGEMENTS_DIR", str(tmp_path / "engagements"))
    monkeypatch.setenv("ARP_ENGAGEMENT_STORE", "postgres")
    get_settings.cache_clear()
    get_engagement_store.cache_clear()
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    get_engagement_store.cache_clear()


@pytest.fixture
def store(pg):
    return PostgresEngagementStore(pg)


@pytest.fixture
def issue(client, store):
    _, opened = store.open_issue("C1", "Acme", theme="climate")
    return opened.issue_id


def _objective(store, issue, **kw) -> str:
    objective = Objective(description="Set a 2030 science-based target", objective_type="strategic", status="in_progress", **kw)
    store.add_objective("C1", issue, objective)
    return objective.objective_id


def _commitment(store, issue, **kw) -> str:
    commitment = Commitment(text="Name a climate committee", target_date="2027-03-31", **kw)
    store.add_commitment("C1", issue, commitment)
    return commitment.commitment_id


def _issue_of(client, issue) -> dict:
    return next(i for i in client.get("/api/engagement/records/C1").json()["issues"] if i["issue_id"] == issue)


def _suggest(dsn, issue, **kw) -> str:
    values = {"kind": "evidence", "company_id": "C1", "engagement_id": issue, "verdict": "found", "doc_id": "doc_1",
              "doc_title": "AR2026.txt", "quote": Q, **kw}  # fmt: skip
    suggestion_id = new_id("evs")
    with transaction(dsn) as s:
        s.add(StwEvidenceSuggestionModel(suggestion_id=suggestion_id, **values))
    return suggestion_id


def _events(store) -> list[str]:
    return [e["event_type"] for e in store.events("C1")]


# --- Schema (AC-1 to AC-3) ---------------------------------------------------------------------------


def _snapshot(dsn):
    insp = inspect(get_engine(dsn))
    with get_engine(dsn).connect() as conn:
        return {
            t: ([c["name"] for c in insp.get_columns(t)], conn.execute(text(f"SELECT count(*) FROM {t}")).scalar())
            for t in STEWARDSHIP_TABLES + WATCH_TABLES
            if t.startswith("stw_")
        }


def test_init_postgres_twice_adds_columns_and_tables_ac1_ac2_ac3(pg):
    for _ in range(2):
        result = CliRunner().invoke(cli, ["db", "init-postgres"])
        assert result.exit_code == 0, result.output
    insp = inspect(get_engine(pg))
    assert "proof_statement" in {c["name"] for c in insp.get_columns("stw_objectives")}
    assert "proof_statement" in {c["name"] for c in insp.get_columns("stw_commitments")}
    assert set(WATCH_TABLES) <= set(insp.get_table_names())
    before = _snapshot(pg)
    assert CliRunner().invoke(cli, ["db", "init-postgres"]).exit_code == 0
    assert _snapshot(pg) == before


# --- Proof statements (AC-4 to AC-7, AC-13, AC-99) -----------------------------------------------------


def test_commitment_with_and_without_proof_statement_ac4_ac5(client, issue):
    body = {"company_id": "C1", "issue_id": issue, "text": "Name a committee", "target_date": "2027-03-31"}
    assert client.post(f"{URL}/tracking/commitments", json=body | {"proof_statement": PROOF}).status_code == 200
    assert client.post(f"{URL}/tracking/commitments", json=body).status_code == 200
    assert [c["proof_statement"] for c in _issue_of(client, issue)["commitments"]] == [PROOF, None]


def test_objective_proof_statement_ac6_ac7(client, store, issue):
    o = _objective(store, issue)
    url = f"{URL}/watch-items/objective/{o}/proof-statement"
    r = client.post(url, json={"company_id": "C1", "issue_id": issue, "proof_statement": PROOF})
    assert r.status_code == 200 and r.json()["proof_statement"] == PROOF
    assert _issue_of(client, issue)["objectives"][0]["proof_statement"] == PROOF
    r = client.post(url, json={"company_id": "C1", "issue_id": issue, "proof_statement": "  "})
    assert (r.status_code, r.json()["detail"]) == (422, "A proof statement cannot be blank.")


def test_proof_statement_on_closed_commitment_and_unknown_ids(client, store, issue):
    c = _commitment(store, issue, status="verified")
    body = {"company_id": "C1", "issue_id": issue, "proof_statement": PROOF}
    assert client.post(f"{URL}/watch-items/commitment/{c}/proof-statement", json=body).status_code == 200  # any status
    for kind, msg in (("objective", "Unknown objective."), ("commitment", "Unknown commitment."), ("topic", "Unknown topic.")):
        r = client.post(f"{URL}/watch-items/{kind}/nope/proof-statement", json=body)
        assert (r.status_code, r.json()["detail"]) == (404, msg)
    _, other = store.open_issue("C1", "Acme", theme="pay")
    r = client.post(f"{URL}/watch-items/commitment/{c}/proof-statement", json=body | {"issue_id": other.issue_id})
    assert (r.status_code, r.json()["detail"]) == (404, "Unknown commitment.")


def test_topic_proof_statement_ac98_ac99(client, issue):
    t = client.post(f"{URL}/watch-topics", json={"company_id": "C1", "issue_id": issue, "question": "Q?", "proof_statement": PROOF}).json()
    assert t["proof_statement"] == PROOF
    t2 = client.post(f"{URL}/watch-topics", json={"company_id": "C1", "issue_id": issue, "question": "Q2?"}).json()
    r = client.post(f"{URL}/watch-items/topic/{t2['topic_id']}/proof-statement", json={"company_id": "C1", "issue_id": issue, "proof_statement": "P"})
    assert r.status_code == 200
    topics = client.get(f"{URL}/watch-topics", params={"company_id": "C1"}).json()["topics"]
    assert {x["topic_id"]: x["proof_statement"] for x in topics} == {t["topic_id"]: PROOF, t2["topic_id"]: "P"}


def test_file_store_carries_proof_statement_ac13(tmp_path):
    files = EngagementStore(tmp_path)
    _, opened = files.open_issue("C1", "Acme", theme="climate")
    files.add_commitment("C1", opened.issue_id, Commitment(text="x", proof_statement=PROOF))
    assert files.get("C1").issues[0].commitments[0].proof_statement == PROOF


# --- Watch topics (AC-8 to AC-10, AC-102, AC-103) ------------------------------------------------------


def test_watch_topic_add_list_close_ac8_ac9_ac10_ac102(client, store, issue):
    body = {"company_id": "C1", "issue_id": issue, "question": "Has the company named a board climate committee?", "target_date": "2027-06-30"}
    r = client.post(f"{URL}/watch-topics", json=body)
    assert r.status_code == 200 and r.json()["status"] == "open" and r.json()["topic_id"].startswith("wtp_")
    topic_id = r.json()["topic_id"]
    listed = client.get(f"{URL}/watch-topics", params={"company_id": "C1"}).json()["topics"]
    assert [(t["topic_id"], t["target_date"], t["created_by"]) for t in listed] == [(topic_id, "2027-06-30", "Test")]
    r = client.post(f"{URL}/watch-topics", json=body | {"question": ""})
    assert (r.status_code, r.json()["detail"]) == (422, "A question is required.")
    r = client.post(f"{URL}/watch-topics", json=body | {"target_date": "30.06.2027"})
    assert (r.status_code, r.json()["detail"]) == (422, "target_date must be an ISO date")
    r = client.post(f"{URL}/watch-topics/{topic_id}/close")
    assert r.status_code == 200 and (r.json()["status"], r.json()["closed_by"]) == ("closed", "Test")
    r = client.post(f"{URL}/watch-topics/{topic_id}/close")
    assert (r.status_code, r.json()["detail"]) == (409, "This topic is already closed.")
    assert client.post(f"{URL}/watch-topics/wtp_nope/close").json()["detail"] == "Unknown topic."
    assert _events(store)[-2:] == ["watch_topic_added", "watch_topic_closed"]


def test_watch_topic_needs_open_engagement_ac103(client, issue):
    assert client.post(f"{URL}/tracking/close", json={"company_id": "C1", "issue_id": issue, "status": "closed", "outcome": "done"}).status_code == 200
    r = client.post(f"{URL}/watch-topics", json={"company_id": "C1", "issue_id": issue, "question": "Q?"})
    assert (r.status_code, r.json()["detail"]) == (409, "Watch topics need an open engagement.")


# --- Objective result (AC-16 to AC-19, AC-100, AC-101) -------------------------------------------------


def test_record_objective_result_ac16(client, store, issue):
    o = _objective(store, issue)
    body = {"company_id": "C1", "issue_id": issue, "result": "achieved", "influence_level": "3", "outcome": "Committee named in the 2026 annual report"}
    assert client.post(f"{URL}/objectives/{o}/result", json=body).status_code == 200
    got = _issue_of(client, issue)["objectives"][0]
    assert (got["status"], got["result"], got["influence_level"], got["outcome"]) == ("closed", "achieved", "3", body["outcome"])
    assert got["closed_at"].startswith(datetime.now(UTC).date().isoformat())
    r = client.post(f"{URL}/objectives/{o}/result", json=body)
    assert (r.status_code, r.json()["detail"]) == (409, "This objective is already closed.")


def test_objective_result_validation_ac17_ac18_ac19_ac101(client, store, issue):
    o = _objective(store, issue)
    body = {"company_id": "C1", "issue_id": issue, "result": "achieved", "outcome": "x"}
    r = client.post(f"{URL}/objectives/{o}/result", json=body)
    assert (r.status_code, r.json()["detail"]) == (422, "An influence level is required to close an objective.")
    r = client.post(f"{URL}/objectives/{o}/result", json=body | {"influence_level": "3", "outcome": "  "})
    assert (r.status_code, r.json()["detail"]) == (422, "An outcome is required.")
    r = client.post(f"{URL}/objectives/obj_unknown/result", json=body | {"influence_level": "3"})
    assert (r.status_code, r.json()["detail"]) == (404, "Unknown objective.")
    assert client.post(f"{URL}/objectives/{o}/result", json=body | {"result": "abandoned"}).status_code == 200
    assert _issue_of(client, issue)["objectives"][0]["status"] == "abandoned"


def test_proof_then_result_writes_two_events_ac100(client, store, issue):
    o = _objective(store, issue)
    before = len(_events(store))
    client.post(f"{URL}/watch-items/objective/{o}/proof-statement", json={"company_id": "C1", "issue_id": issue, "proof_statement": PROOF})
    client.post(f"{URL}/objectives/{o}/result", json={"company_id": "C1", "issue_id": issue, "result": "achieved", "influence_level": "3", "outcome": "x"})
    assert _events(store)[before:] == ["proof_statement_set", "objective_result_recorded"]


# --- Suggestions (AC-15, AC-47, AC-48, and the confirm paths PR 2's rows rely on) ------------------------


def _pending(client, status="pending"):
    return client.get(f"{URL}/evidence-suggestions", params={"company_id": "C1", "status": status}).json()["suggestions"]


def test_unknown_suggestion_ac15(client):
    r = client.post(f"{URL}/evidence-suggestions/evs_unknown/confirm")
    assert (r.status_code, r.json()["detail"]) == (404, "Unknown suggestion.")


def test_confirm_found_verifies_and_resolves(client, pg, issue, store):
    c = _commitment(store, issue)
    s = _suggest(pg, issue, item_kind="commitment", item_id=c)
    assert [x["suggestion_id"] for x in _pending(client)] == [s]
    assert client.post(f"{URL}/evidence-suggestions/{s}/confirm").status_code == 200
    got = _issue_of(client, issue)
    assert (got["commitments"][0]["status"], got["commitments"][0]["validated_by"]) == ("verified", "Test")
    assert got["commitments"][0]["evidence"] == f'AR2026.txt: "{Q}"'
    assert got["status"] == "resolved"  # its only commitment, as Verify does
    confirmed = _pending(client, "confirmed")
    assert (confirmed[0]["decided_by"], confirmed[0]["decided_at"] is not None) == ("Test", True)
    r = client.post(f"{URL}/evidence-suggestions/{s}/reject", json={"reason": "r"})
    assert (r.status_code, r.json()["detail"]) == (409, "Suggestion already confirmed.")


def test_confirm_against_with_page_ac48(client, pg, issue, store):
    c = _commitment(store, issue)
    s = _suggest(pg, issue, item_kind="commitment", item_id=c, verdict="against", doc_title="AR 2026.pdf", page=4)
    assert client.post(f"{URL}/evidence-suggestions/{s}/confirm").status_code == 200
    got = _issue_of(client, issue)["commitments"][0]
    assert (got["status"], got["evidence"]) == ("missed", f'AR 2026.pdf, page 4: "{Q}"')


def test_confirm_objective_and_topic_change_nothing_on_the_item(client, pg, issue, store):
    o = _objective(store, issue)
    t = client.post(f"{URL}/watch-topics", json={"company_id": "C1", "issue_id": issue, "question": "Q?"}).json()["topic_id"]
    for kind, item in (("objective", o), ("topic", t)):
        assert client.post(f"{URL}/evidence-suggestions/{_suggest(pg, issue, item_kind=kind, item_id=item)}/confirm").status_code == 200
    assert _issue_of(client, issue)["objectives"][0]["status"] == "in_progress"
    assert client.get(f"{URL}/watch-topics", params={"company_id": "C1"}).json()["topics"][0]["status"] == "open"
    assert {x["item_kind"] for x in _pending(client, "confirmed")} == {"objective", "topic"}


def test_confirm_on_closed_item_is_409_and_stays_pending(client, pg, issue, store):
    c = _commitment(store, issue)
    s = _suggest(pg, issue, item_kind="commitment", item_id=c)
    client.post(f"{URL}/tracking/commitments/{c}", json={"company_id": "C1", "issue_id": issue, "status": "verified", "evidence": "e"})
    r = client.post(f"{URL}/evidence-suggestions/{s}/confirm")
    assert (r.status_code, r.json()["detail"]) == (409, "This item is no longer open.")
    assert [x["suggestion_id"] for x in _pending(client)] == [s]


def test_reject_keeps_reason_and_events_ac47(client, pg, issue, store):
    c1, c2 = _commitment(store, issue), _commitment(store, issue)
    s1, s2 = _suggest(pg, issue, item_kind="commitment", item_id=c1), _suggest(pg, issue, item_kind="commitment", item_id=c2)
    r = client.post(f"{URL}/evidence-suggestions/{s2}/reject", json={"reason": "  "})
    assert (r.status_code, r.json()["detail"]) == (422, "A reason is required to reject a suggestion.")
    assert client.post(f"{URL}/evidence-suggestions/{s2}/reject", json={"reason": "Quote is about the 2024 target"}).status_code == 200
    assert client.post(f"{URL}/evidence-suggestions/{s1}/confirm").status_code == 200
    assert _pending(client, "rejected")[0]["reject_reason"] == "Quote is about the 2024 target"
    assert _pending(client) == []
    r = client.post(f"{URL}/evidence-suggestions/{s2}/confirm")
    assert (r.status_code, r.json()["detail"]) == (409, "Suggestion already rejected.")
    events = {e["event_type"]: e for e in store.events("C1") if e["event_type"].startswith("evidence_suggestion_")}
    assert (events["evidence_suggestion_confirmed"]["suggestion_id"], events["evidence_suggestion_rejected"]["suggestion_id"]) == (s1, s2)
    assert _issue_of(client, issue)["commitments"][1]["status"] == "open"


def test_confirm_new_commitment(client, pg, issue, store):
    entry = CorrespondenceEntry(type="meeting", summary="The CFO committed.", date="2026-10-01T09:00:00+00:00")
    store.add_correspondence("C1", issue, entry)
    s = _suggest(pg, issue, kind="new_commitment", activity_id=entry.entry_id, item_kind=None, verdict=None, doc_id=None,
                 text="Publish a transition plan", quote="The CFO committed.")  # fmt: skip
    r = client.post(f"{URL}/evidence-suggestions/{s}/confirm", json={})
    assert (r.status_code, r.json()["detail"]) == (422, "A due date is required to add a commitment.")
    r = client.post(f"{URL}/evidence-suggestions/{s}/confirm", json={"target_date": "31.03.2027"})
    assert (r.status_code, r.json()["detail"]) == (422, "target_date must be an ISO date")
    assert _issue_of(client, issue)["commitments"] == []
    r = client.post(f"{URL}/evidence-suggestions/{s}/confirm", json={"target_date": "2027-03-31"})
    assert r.status_code == 200
    made = _issue_of(client, issue)["commitments"][0]
    assert (made["text"], made["target_date"], made["recorded_by"]) == ("Publish a transition plan", "2027-03-31", "Test")
    assert made["made_at"].startswith("2026-10-01")
    assert r.json()["created_commitment_id"] == made["commitment_id"]


# --- Store and auth guards (AC-11, AC-12, AC-14) -------------------------------------------------------


@pytest.fixture
def file_client(pg, monkeypatch, tmp_path):  # the app needs Postgres to start; the engagement store is the file one
    monkeypatch.setenv("ARP_ENGAGEMENTS_DIR", str(tmp_path / "engagements"))
    monkeypatch.setenv("ARP_ENGAGEMENT_STORE", "file")
    get_settings.cache_clear()
    get_engagement_store.cache_clear()
    with TestClient(app) as c:
        yield c
    get_engagement_store.cache_clear()


def test_file_store_answers_409_ac11_ac12(file_client):
    msg = "Watch items need the Postgres engagement store."
    r = file_client.get(f"{URL}/watch-topics", params={"company_id": "x"})
    assert (r.status_code, r.json()["detail"]) == (409, msg)
    r = file_client.post(f"{URL}/watch-items/commitment/cmt_1/check", json={"company_id": "x"})
    assert (r.status_code, r.json()["detail"]) == (409, msg)


def test_viewer_cannot_confirm_ac14(tmp_path, pg):
    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": [{"token": "tv", "user_id": "u", "name": "V", "role": "viewer"}]}))
    app.dependency_overrides.clear()  # an autouse fixture signs everyone in
    app.dependency_overrides[settings_dep] = lambda: Settings(users_file=users, auth_mode="local")
    try:
        r = TestClient(app).post(f"{URL}/evidence-suggestions/evs_1/confirm", headers={"Authorization": "Bearer tv"})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 403
