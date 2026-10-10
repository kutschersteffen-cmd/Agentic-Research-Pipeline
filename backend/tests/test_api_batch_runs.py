"""Every run-start route takes `batch: true`: the run is marked and its pipeline gets batching clients."""
import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps, run_scheduling
from arp.api.routers import extraction, financials, identity, themes, tnfd, transition_plan, voting
from arp.config import Settings
from arp.llm.batching_client import BatchingLLMClient
from arp.orchestration.job_manager import JobManager
from arp.storage.run_store import RunStore

COMPANIES = [{"company_id": "c1", "name": "Acme"}]
SCHEMA = {"schema_id": "s", "name": "s", "fields": []}
THEME = {"name": "t", "description": "d"}

# router, url, create_*, execute_*, body
ROUTES = {
    "extraction": (extraction, "/api/extraction/runs", "create_extraction_run", "execute_extraction_run", {"datapoint_schema": SCHEMA}),
    "financials": (financials, "/api/financials/runs", "create_financials_extraction_run", "execute_financials_extraction_run", {}),
    "tnfd": (tnfd, "/api/tnfd/runs", "create_tnfd_extraction_run", "execute_tnfd_extraction_run", {"as_of": "FY2025"}),
    "transition_plan": (transition_plan, "/api/transition-plan/runs", "create_transition_plan_run", "execute_transition_plan_run", {}),
    "themes": (themes, "/api/themes/runs", "create_theme_run", "execute_theme_run", {"theme": THEME}),
    "voting": (voting, "/api/voting/runs", "create_voting_run", "execute_voting_run", {}),
    "identity": (identity, "/api/identity/runs", "create_identity_run", "execute_identity_run", {}),
}


JOBS: list = []


class _Launcher:
    def launch(self, run_id, job):
        JOBS.append(job)  # run after the request: the endpoint's own loop is still running


@pytest.fixture
def start(tmp_path, monkeypatch):
    settings = Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")
    store = RunStore(settings.runs_dir)
    seen: dict = {}
    JOBS.clear()
    monkeypatch.setattr(run_scheduling, "get_job_launcher", _Launcher)
    monkeypatch.setattr(run_scheduling, "get_llm_client", lambda: "rt-llm")
    monkeypatch.setattr(run_scheduling, "get_verifier_llm_client", lambda: "rt-verifier")

    def go(name: str, **extra):
        module, url, create, execute, body = ROUTES[name]

        def _create(*_a, **_k):
            return JobManager(store).create_run(name, {}, 1).run_id

        async def _execute(run_id, *_a, **kwargs):
            seen["llm"], seen["verifier"], seen["settings"] = kwargs.get("llm"), kwargs.get("verifier_llm"), kwargs.get("settings")

        monkeypatch.setattr(module, create, _create)
        monkeypatch.setattr(module, execute, _execute)
        app = FastAPI()
        app.include_router(module.router)
        app.dependency_overrides[deps.settings_dep] = lambda: settings
        app.dependency_overrides[deps.get_run_store] = lambda: store
        for dep in (deps.get_registry, deps.get_decision_store, deps.get_xbrl_source, deps.get_taxonomy_store,
                    deps.get_engagement_store, deps.get_edgar_source, deps.get_web_search_client):
            app.dependency_overrides[dep] = lambda: None
        res = TestClient(app).post(url, json={"companies": COMPANIES, **body, **extra})
        assert res.status_code == 200, res.text
        asyncio.run(JOBS[0]())
        return store.load_manifest(res.json()["run_id"]).params, seen

    return go


@pytest.mark.parametrize("name", ROUTES)
def test_batch_true_marks_run_and_batches_clients(start, name):
    params, seen = start(name, batch=True)
    assert params["batch"] is True
    assert isinstance(seen["llm"], BatchingLLMClient)
    if name not in ("voting", "identity"):
        assert isinstance(seen["verifier"], BatchingLLMClient)
    assert seen["settings"].llm_batch and seen["settings"].max_concurrent_llm_calls == 1000


@pytest.mark.parametrize("name", ROUTES)
def test_without_batch_nothing_changes(start, name):
    params, seen = start(name)
    assert "batch" not in params
    assert not isinstance(seen["llm"], BatchingLLMClient)
    assert not seen["settings"].llm_batch if name != "identity" else True
