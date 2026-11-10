"""Argus step 4's Retry: one failed company re-runs inside the same run, on the flow's current kept files."""

import json

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_run_store, settings_dep
from arp.api.main import app
from arp.api.routers import argus as argus_router
from arp.argus.flows import FlowStore
from arp.config import Settings
from arp.orchestration import jobs
from arp.orchestration.job_manager import JobManager
from arp.schemas.common import JobStatus, RunManifest
from arp.storage.run_store import RunStore
from tests.pdf_fixtures import FILLER, make_pdf
from tests.test_resume_run import COMPANIES, _resume, _settings, _theme_run


async def test_resume_one_company_keeps_the_other_failures(tmp_path, pg, monkeypatch):
    settings = _settings(tmp_path)
    store = RunStore(pg, settings.runs_dir)
    run_id = _theme_run(COMPANIES[:3], settings, store)
    store.append_result(run_id, {"_key": "c3", "company_id": "c3"})
    store.append_error(run_id, {"key": "c2", "error": "boom"})  # c1's row was cleared by Retry
    JobManager(store).record_progress(run_id, completed_delta=1, failed_delta=2)
    JobManager(store).finish_run(run_id)
    seen = {}

    async def fake_resume(run_id, manifest, companies, **_):
        seen["companies"] = [c.company_id for c in companies]
        seen["manifest"] = store.load_manifest(run_id)
        return run_id

    monkeypatch.setitem(jobs._RESUME, "theme", fake_resume)
    await _resume(run_id, settings, store, company_ids=["c1"])
    assert seen["companies"] == ["c1"]  # c2 is not retried
    m = seen["manifest"]
    assert (m.completed_count, m.failed_count, m.status) == (1, 1, JobStatus.RUNNING)  # c2 still counts as failed


@pytest.fixture
def settings(tmp_path, pg):
    return Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache",
                    documents_dir=tmp_path / "docs", discovery_state_dir=tmp_path / "state", postgres_dsn=pg)


@pytest.fixture
def run_store(settings, pg):
    return RunStore(pg, settings.runs_dir)


@pytest.fixture
def client(settings, run_store):
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[get_run_store] = lambda: run_store
    yield TestClient(app)
    app.dependency_overrides.pop(settings_dep, None)
    app.dependency_overrides.pop(get_run_store, None)


@pytest.fixture
def launched(monkeypatch):
    calls: list = []

    class Launcher:
        def launch(self, run_id, job, *, run_store=None):
            calls.append(run_id)
            job().close()  # the coroutine is not run here; only that it was launched

    monkeypatch.setattr(argus_router, "get_job_launcher", Launcher)
    monkeypatch.setattr(argus_router, "check_resumable", lambda store, run_id: None)
    return calls


@pytest.fixture
def flow(client, settings, run_store, tmp_path):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    client.post(f"/api/argus/flows/{fid}/companies/upload", files={"file": ("u.csv", "name,company_id\nApple Inc,aapl\nMicrosoft Corporation,msft\n")})
    client.patch(f"/api/argus/flows/{fid}", json={"reporting_year": 2025})
    data = make_pdf(tmp_path / "a.pdf", ["Apple Inc Annual Report 2025", FILLER], n_pages=2).read_bytes()
    client.post(f"/api/argus/flows/{fid}/documents/upload", data={"company_id": "aapl", "doc_type": "10-K"},
                files={"file": ("a.pdf", data, "application/pdf")})
    client.post(f"/api/argus/flows/{fid}/files", json={"all_that_pass": True})
    run_store.save_manifest(RunManifest(run_id="extraction_r", run_type="extraction", company_count=2,
                                        status="partially_completed", failed_count=1, completed_count=1))
    run_dir = run_store.run_dir("extraction_r")
    (run_dir / "start_request.json").write_text(json.dumps({"profile": "custom", "companies": [
        {"company_id": "aapl", "name": "Apple Inc"}, {"company_id": "msft", "name": "Microsoft Corporation"}]}))
    (run_dir / "only_documents.json").write_text(json.dumps({"aapl": ["old"], "msft": ["m"]}))
    run_store.append_result("extraction_r", {"_key": "msft", "company_id": "msft", "name": "Microsoft Corporation", "fields": []})
    run_store.append_error("extraction_r", {"key": "aapl", "error": "No text could be read from old.pdf", "document_problem": True})
    FlowStore(settings.runs_dir / "_flows").update(fid, lambda f: (setattr(f, "run_id", "extraction_r"), setattr(f, "step", 4)))
    return fid


def test_retry_runs_one_company_on_the_current_kept_files(client, flow, launched, run_store):
    r = client.post(f"/api/argus/flows/{flow}/companies/aapl/retry")
    assert r.status_code == 200, r.text
    assert launched == ["extraction_r"]
    assert run_store.read_errors("extraction_r") == []  # AC-38: the row leaves Failed at once
    only = json.loads((run_store.run_dir("extraction_r") / "only_documents.json").read_text())
    assert only["msft"] == ["m"] and only["aapl"] != ["old"] and len(only["aapl"]) == 1  # the file kept now
    rows = {c["company_id"]: c["status"] for c in client.get(f"/api/argus/flows/{flow}/progress").json()["companies"]}
    assert rows == {"aapl": "Stopped", "msft": "Done"}  # until the launched job marks the run running


def test_retry_refuses_a_running_run_and_a_company_that_did_not_fail(client, flow, launched, run_store):
    assert client.post(f"/api/argus/flows/{flow}/companies/msft/retry").status_code == 400
    m = run_store.load_manifest("extraction_r")
    m.status = JobStatus.RUNNING
    run_store.save_manifest(m)
    assert client.post(f"/api/argus/flows/{flow}/companies/aapl/retry").status_code == 409
    assert launched == []
