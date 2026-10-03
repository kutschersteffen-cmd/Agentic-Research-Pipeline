"""Four-eyes on index calibrations: the author cannot be the approver."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import get_index_store
from arp.api.routers import index as index_router
from arp.storage.index_store import IndexStore

ALICE = Principal(user_id="u_alice", name="Alice", role="approver")
BOB = Principal(user_id="u_bob", name="Bob", role="approver")


@pytest.fixture
def api(tmp_path):
    app = FastAPI()
    app.include_router(index_router.router)
    store = IndexStore(tmp_path)
    app.dependency_overrides[get_index_store] = lambda: store
    who = {"p": ALICE}
    app.dependency_overrides[current_user] = lambda: who["p"]
    client = TestClient(app)
    client.as_user = lambda p: who.__setitem__("p", p)
    client.store = store
    return client


def _create(api, **extra) -> dict:
    spec = api.get("/api/index/presets/exclusion_only").json()
    r = api.post("/api/index/calibrations", json={"name": "c", "effective_from": "2026-01-01", "spec": spec, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _run(api, cal_id: str):
    return api.post("/api/index/run", json={"review_date": "2026-03-31", "calibration_id": cal_id})


def test_creator_cannot_approve_own_calibration(api):
    cal = _create(api)
    assert cal["created_by"] == "u_alice"
    r = api.post(f"/api/index/calibrations/{cal['calibration_id']}/approve")
    assert r.status_code == 400
    assert api.get(f"/api/index/calibrations/{cal['calibration_id']}").json()["approved_by"] == []


def test_other_approver_approves(api):
    cal = _create(api)
    api.as_user(BOB)
    r = api.post(f"/api/index/calibrations/{cal['calibration_id']}/approve")
    assert r.status_code == 200
    assert r.json()["approved_by"] == ["u_bob"]
    assert _run(api, cal["calibration_id"]).status_code == 200


def test_unapproved_calibration_blocks_review_run(api):
    cal = _create(api)
    assert _run(api, cal["calibration_id"]).status_code == 404
    api.post(f"/api/index/calibrations/{cal['calibration_id']}/approve")  # self-approval refused
    assert _run(api, cal["calibration_id"]).status_code == 404


def test_new_version_needs_its_own_approval(api):
    cal = _create(api)
    cid = cal["calibration_id"]
    api.as_user(BOB)
    api.post(f"/api/index/calibrations/{cid}/approve")
    spec = api.get("/api/index/presets/exclusion_only").json()
    v2 = api.post(f"/api/index/calibrations/{cid}/versions", json={"name": "c", "effective_from": "2026-02-01", "spec": spec})
    assert v2.json()["created_by"] == "u_bob" and v2.json()["approved_by"] == []
    assert _run(api, cid).status_code == 404
    api.as_user(ALICE)
    assert api.post(f"/api/index/calibrations/{cid}/approve").status_code == 200
    assert _run(api, cid).status_code == 200


def test_approved_by_in_body_ignored(api):
    cal = _create(api, approved_by=["u_bob"])
    assert cal["approved_by"] == []
    assert _run(api, cal["calibration_id"]).status_code == 404


def test_legacy_calibration_without_created_by(api):
    spec = api.get("/api/index/presets/exclusion_only").json()
    legacy = api.store.create_calibration("old", index_router.ConstructionSpec(**spec), effective_from="2026-01-01", approved_by=["IC-2026-06-11"])
    unapproved = api.store.create_calibration("old2", index_router.ConstructionSpec(**spec), effective_from="2026-01-01")
    assert legacy.created_by is None
    assert _run(api, legacy.calibration_id).status_code == 200
    assert _run(api, unapproved.calibration_id).status_code == 404
