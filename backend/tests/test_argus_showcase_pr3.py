"""showcase-argus-fixes, PR 3: the two server pieces behind the browser fixes.

XBRL `Add one company` extends the picked list into a new one (AC-129 to AC-133, AC-152, AC-153), and a run's
companies name the central id their company link opens (AC-127)."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.routers import universe as universe_router
from arp.api.routers.extraction import run_companies
from arp.config import Settings
from arp.orchestration.job_manager import JobManager
from arp.storage.run_store import RunStore


@pytest.fixture
def client(tmp_path):
    settings = Settings(runs_dir=tmp_path / "runs")
    app = FastAPI()
    app.include_router(universe_router.router)
    app.dependency_overrides[deps.settings_dep] = lambda: settings
    return TestClient(app)


def _add(client, company, base=None):
    body = {"companies": [company], "name": "single", **({"base_path": base} if base else {})}
    r = client.post("/api/universe/from-companies", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _ids(path):
    return [c["company_id"] for c in json.loads(Path(path).read_text())]


MSFT = {"company_id": "789019", "name": "Microsoft", "cik": "789019"}


def test_add_one_extends_the_picked_list_into_a_new_one(client):
    first = client.post("/api/universe/upload", files={"file": ("one.csv", "company_id,name\naapl,Apple\n", "text/plain")}).json()
    added = _add(client, MSFT, first["path"])
    assert added["company_count"] == 2 and added["path"] != first["path"]  # AC-129
    assert _ids(added["path"]) == ["aapl", "789019"]
    assert client.post("/api/universe/upload", files={"file": ("one.csv", "company_id,name\naapl,Apple\n", "text/plain")}).json()["company_count"] == 1
    again = _add(client, MSFT, added["path"])
    assert again["company_count"] == 2  # AC-132: the same company is not added twice


def test_the_picked_list_is_not_changed(client, tmp_path):
    saved = tmp_path / "runs" / "_universes"
    saved.mkdir(parents=True)
    (saved / "one.json").write_text(json.dumps([{"company_id": "aapl", "name": "Apple"}]))
    _add(client, MSFT, str(saved / "one.json"))
    assert _ids(saved / "one.json") == ["aapl"]  # AC-152


def test_add_one_with_nothing_picked_is_a_list_of_one(client):
    assert _add(client, MSFT)["company_count"] == 1  # AC-131


def test_a_base_outside_the_saved_universes_is_refused(client, tmp_path):
    outside = tmp_path / "x.json"
    outside.write_text(json.dumps([{"company_id": "a", "name": "A"}]))
    r = client.post("/api/universe/from-companies", json={"companies": [MSFT], "base_path": str(outside)})
    assert r.status_code == 400 and r.json()["detail"] == "Universe file must be a saved universe."


def test_a_runs_companies_name_their_central_id(tmp_path, pg):
    store = RunStore(pg, tmp_path)
    run_id = JobManager(store).create_run("extraction", {}, 2).run_id
    central = str(uuid.uuid4())
    (store.run_dir(run_id) / "start_request.json").write_text(json.dumps({"profile": "custom", "companies": [
        {"company_id": "aapl", "name": "Apple", "entity_id": central}, {"company_id": "acme", "name": "Acme"}]}))
    rows = run_companies(store, run_id, [], [])
    assert [(r["company_id"], r["entity_id"]) for r in rows] == [("aapl", central), ("acme", None)]  # AC-127


def test_a_base_path_that_is_no_path_is_refused(client):
    r = client.post("/api/universe/from-companies", json={"companies": [MSFT], "base_path": "bad\x00path.json"})
    assert r.status_code == 400 and r.json()["detail"] == "Universe file must be a saved universe."


def test_an_unreadable_base_is_refused(client, tmp_path):
    saved = tmp_path / "runs" / "_universes"
    saved.mkdir(parents=True)
    (saved / "broken.json").write_text("{not json")
    r = client.post("/api/universe/from-companies", json={"companies": [MSFT], "base_path": str(saved / "broken.json")})
    assert r.status_code == 400 and r.json()["detail"] == "Could not read the universe file."
