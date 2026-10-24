"""Runs record who started them: params.started_by, which the Argus start page shows and filters on."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps, run_scheduling
from arp.api.auth import Principal, current_user
from arp.api.routers import extraction, financials
from arp.config import Settings
from arp.orchestration.job_manager import JobManager
from arp.storage.run_store import RunStore


def test_set_started_by_writes_params(pg, tmp_path):
    store = RunStore(pg, tmp_path)
    jm = JobManager(store)
    m = jm.create_run("extraction", {"schema_name": "S"}, 1)
    jm.set_started_by(m.run_id, "alice")
    assert store.load_manifest(m.run_id).params == {"schema_name": "S", "started_by": "alice"}


@pytest.fixture
def client(tmp_path, monkeypatch, pg):
    settings = Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")
    store = RunStore(pg, settings.runs_dir)
    jobs: list = []

    class _Launcher:
        def launch(self, run_id, job):
            jobs.append(job)

    monkeypatch.setattr(run_scheduling, "get_job_launcher", _Launcher)
    monkeypatch.setattr(run_scheduling, "get_llm_client", lambda: "llm")
    monkeypatch.setattr(run_scheduling, "get_verifier_llm_client", lambda: "verifier")
    for module, create, execute in ((extraction, "create_extraction_run", "execute_extraction_run"),
                                    (financials, "create_financials_extraction_run", "execute_financials_extraction_run")):
        monkeypatch.setattr(module, create, lambda *_a, _t=module.__name__, **_k: JobManager(store).create_run(_t, {}, 1).run_id)

        async def _execute(*_a, **_k):
            return None

        monkeypatch.setattr(module, execute, _execute)
    app = FastAPI()
    app.include_router(extraction.router)
    app.include_router(financials.router)
    app.dependency_overrides[deps.settings_dep] = lambda: settings
    app.dependency_overrides[deps.get_run_store] = lambda: store
    for dep in (deps.get_registry, deps.get_decision_store, deps.get_xbrl_source):
        app.dependency_overrides[dep] = lambda: None
    app.dependency_overrides[current_user] = lambda: Principal(user_id="alice", name="Alice", role="analyst")
    return TestClient(app), store


def test_extraction_runs_records_the_signed_in_user(client):
    c, store = client
    r = c.post("/api/extraction/runs", json={"companies": [{"company_id": "c1", "name": "Acme"}],
                                             "datapoint_schema": {"schema_id": "s", "name": "s", "fields": []}})
    assert r.status_code == 200, r.text
    assert store.load_manifest(r.json()["run_id"]).params["started_by"] == "alice"


def test_extraction_start_records_the_signed_in_user(client):
    c, store = client
    r = c.post("/api/extraction/start", json={"profile": "financials", "companies": [{"company_id": "c1", "name": "Acme"}]})
    assert r.status_code == 200, r.text
    assert store.load_manifest(r.json()["run_id"]).params["started_by"] == "alice"


def test_without_started_by_params_stay_untouched(pg, tmp_path, monkeypatch):
    store = RunStore(pg, tmp_path)
    monkeypatch.setattr(run_scheduling, "get_job_launcher", lambda: type("L", (), {"launch": lambda self, r, j: None})())
    monkeypatch.setattr(run_scheduling, "get_llm_client", lambda: "llm")
    monkeypatch.setattr(run_scheduling, "get_verifier_llm_client", lambda: "verifier")

    async def _run(*_a):
        return None

    run_id = run_scheduling.schedule_llm_run(create_fn=lambda: JobManager(store).create_run("x", {}, 1).run_id, run=_run, run_store=store)
    assert "started_by" not in store.load_manifest(run_id).params
