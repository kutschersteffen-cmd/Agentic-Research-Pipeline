"""Four-eyes on index calibrations: the author cannot be the approver."""

from __future__ import annotations

import json

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


def test_legacy_calibration_without_created_by(api, tmp_path):
    spec = api.get("/api/index/presets/exclusion_only").json()
    ids = {}
    for name, approvals in (("old", ["IC-2026-06-11"]), ("old2", [])):
        cal = api.store.create_calibration(name, index_router.ConstructionSpec(**spec), effective_from="2026-01-01", created_by="x")
        path = tmp_path / "calibrations" / cal.calibration_id / "v1.json"
        data = json.loads(path.read_text())
        data.pop("created_by")
        data["approved_by"] = approvals
        path.write_text(json.dumps(data))
        ids[name] = cal.calibration_id
    # Pre-four-eyes data is grandfathered: both resolve, with or without a recorded approval.
    assert _run(api, ids["old"]).status_code == 200
    assert _run(api, ids["old2"]).status_code == 200


@pytest.fixture
def cli(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from arp.cli import index as cli_index
    from arp.config import Settings

    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": [
        {"user_id": "u_alice", "name": "Alice", "role": "approver", "token": "ta"},
        {"user_id": "u_bob", "name": "Bob", "role": "approver", "token": "tb"},
        {"user_id": "u_ana", "name": "Ana", "role": "analyst", "token": "tn"},
    ]}))
    settings = Settings(indices_dir=tmp_path / "idx", users_file=users)
    monkeypatch.setattr(cli_index, "get_settings", lambda: settings)

    def run(token, *args):
        monkeypatch.setenv("ARP_CLI_TOKEN", token)
        return CliRunner().invoke(cli_index.index_app, list(args))

    run.store = IndexStore(settings.indices_dir)
    return run


def test_cli_calibration_unapproved_until_second_principal_approves(cli):
    r = cli("ta", "calibration-save", "--name", "c", "--effective-from", "2026-01-01", "--preset", "exclusion_only",
            "--approved-by", "IC-1")
    assert r.exit_code == 0, r.output
    cal = cli.store.list_calibrations()[0]
    assert cal.created_by == "u_alice" and cal.approved_by == [] and "IC-1" in cal.notes
    run = ("--index-id", "i", "--review-date", "2026-03-31", "--calibration-id", cal.calibration_id)
    assert cli("ta", "run", *run).exit_code != 0
    assert cli("tb", "approve", cal.calibration_id).exit_code == 0
    assert cli("ta", "run", *run).exit_code == 0


def test_cli_author_cannot_approve(cli):
    cli("ta", "calibration-save", "--name", "c", "--effective-from", "2026-01-01", "--preset", "exclusion_only")
    cal = cli.store.list_calibrations()[0]
    assert cli("ta", "approve", cal.calibration_id).exit_code == 1
    assert cli.store.get_calibration(cal.calibration_id).approved_by == []


def test_cli_analyst_cannot_approve(cli):
    cli("ta", "calibration-save", "--name", "c", "--effective-from", "2026-01-01", "--preset", "exclusion_only")
    cal = cli.store.list_calibrations()[0]
    r = cli("tn", "approve", cal.calibration_id)
    assert r.exit_code == 1 and "approver" in r.output
    assert cli.store.get_calibration(cal.calibration_id).approved_by == []
