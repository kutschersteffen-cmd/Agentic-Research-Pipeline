"""An unconfigured LLM key must not leave a run manifest behind.

`api/run_scheduling.schedule_llm_run` exists to resolve the LLM clients
before `create_fn` runs, precisely so a failed key check cannot strand a
manifest in "running" with no task that will ever call `finish_run()`.
This endpoint hand-rolled `asyncio.create_task` and created the manifest
first, reintroducing the bug the helper was written for -- so the helper's
own prediction, that "a sixth run-creation endpoint gets the fix for
free", only holds while endpoints actually go through it.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import run_scheduling
from arp.api.deps import get_taxonomy_store, settings_dep
from arp.api.routers import taxonomy_researcher as router_module
from arp.config import Settings
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore


@pytest.fixture
def client(tmp_path):
    settings = Settings(runs_dir=tmp_path / "runs", taxonomies_dir=tmp_path / "taxonomies")
    settings.ensure_dirs()
    run_store = RunStore(settings.runs_dir)

    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[router_module._run_store] = lambda: run_store
    app.dependency_overrides[get_taxonomy_store] = lambda: TaxonomyStore(settings.taxonomies_dir)

    with TestClient(app, raise_server_exceptions=False) as c:
        c.run_store = run_store
        yield c


def test_unconfigured_llm_leaves_no_orphaned_run(client, monkeypatch):
    def _no_key() -> None:
        raise RuntimeError("No API key configured")

    # schedule_llm_run resolves the client, so patch it where it is looked up.
    monkeypatch.setattr(run_scheduling, "get_llm_client", _no_key)

    response = client.post("/api/taxonomy-researcher/runs", json={})

    assert response.status_code >= 400
    # The real defect: the manifest used to be written before the key check,
    # so a failed request left a run that stayed "running" forever.
    assert client.run_store.list_runs() == []
