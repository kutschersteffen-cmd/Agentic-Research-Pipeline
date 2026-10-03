from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import get_run_store
from arp.api.routers import extraction as extraction_router
from arp.orchestration.review_queue import effective_decisions, record_cosign, record_review_decision
from arp.storage.run_store import RunStore

ALICE = Principal(user_id="u_alice", name="Alice", role="approver")
BOB = Principal(user_id="u_bob", name="Bob", role="approver")
REQ = {"edit"}


@pytest.fixture
def run_store(tmp_path):
    return RunStore(tmp_path / "runs")


def _edit(rs, who=ALICE):
    record_review_decision(rs, "r1", "k", "edit", None, {"v": 1}, principal=who)


def test_cosign_by_same_user_refused(run_store):
    _edit(run_store)
    with pytest.raises(ValueError, match="different person"):
        record_cosign(run_store, "r1", "k", ALICE)


def test_cosign_compares_user_id_not_name(run_store):
    _edit(run_store)
    with pytest.raises(ValueError, match="different person"):
        record_cosign(run_store, "r1", "k", Principal(user_id="u_alice", name="ALICE", role="approver"))


def test_cosign_without_decision_refused(run_store):
    with pytest.raises(ValueError, match="nothing to co-sign"):
        record_cosign(run_store, "r1", "k", BOB)


def test_uncosigned_edit_not_effective(run_store):
    _edit(run_store)
    record_review_decision(run_store, "r1", "a", "approve", None, None, principal=ALICE)
    assert set(effective_decisions(run_store, "r1", cosign_required=REQ)) == {"a"}


def test_cosigned_edit_effective(run_store):
    _edit(run_store)
    record_cosign(run_store, "r1", "k", BOB)
    assert "k" in effective_decisions(run_store, "r1", cosign_required=REQ)


def test_new_decision_after_cosign_needs_new_cosign(run_store):
    _edit(run_store)
    record_cosign(run_store, "r1", "k", BOB)
    _edit(run_store)
    assert "k" not in effective_decisions(run_store, "r1", cosign_required=REQ)


def test_legacy_decision_without_user_id_can_be_cosigned(run_store):
    record_review_decision(run_store, "r1", "k", "edit", "old", {"v": 1})
    record_cosign(run_store, "r1", "k", BOB)
    assert "k" in effective_decisions(run_store, "r1", cosign_required=REQ)


def _client(run_store, who):
    app = FastAPI()
    app.include_router(extraction_router.router)
    app.dependency_overrides[get_run_store] = lambda: run_store
    app.dependency_overrides[current_user] = lambda: who
    return TestClient(app)


def test_cosign_route_requires_approver(run_store):
    _edit(run_store)
    r = _client(run_store, Principal(user_id="u_an", name="An", role="analyst")).post(
        "/api/extraction/runs/r1/cosign", json={"item_key": "k"}
    )
    assert r.status_code == 403


def test_cosign_route_ok_and_same_user_400(run_store):
    _edit(run_store)
    assert _client(run_store, ALICE).post("/api/extraction/runs/r1/cosign", json={"item_key": "k"}).status_code == 400
    assert _client(run_store, BOB).post("/api/extraction/runs/r1/cosign", json={"item_key": "k"}).status_code == 200
