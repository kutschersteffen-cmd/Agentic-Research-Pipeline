"""Argus step 4's Retry: one failed company re-runs inside the same run, on the flow's current kept files."""

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_run_store, settings_dep
from arp.api.main import app
from arp.api.routers import argus as argus_router
from arp.argus.flows import FlowStore
from arp.config import Settings
from arp.orchestration import jobs
from arp.orchestration.job_manager import JobManager
from arp.schemas.common import CompanyRef, JobStatus, RunManifest
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
    with TestClient(app) as c:  # keeps the app's loop alive for the job the real LocalJobLauncher starts
        yield c
    app.dependency_overrides.pop(settings_dep, None)
    app.dependency_overrides.pop(get_run_store, None)


@pytest.fixture
def resumed(monkeypatch, run_store):
    """resume_run, faked: it records what the launched job saw once it held the run; `fail` makes it raise."""
    seen: dict = {"calls": [], "fail": False, "delay": 0.0}

    async def fake(run_id, *, company_ids, **_):
        await asyncio.sleep(seen["delay"])
        seen["calls"].append(company_ids)
        seen["errors"] = run_store.read_errors(run_id)
        seen["only"] = json.loads((run_store.run_dir(run_id) / "only_documents.json").read_text())
        if seen["fail"]:
            raise RuntimeError("model setup failed")
        return run_id

    monkeypatch.setattr(argus_router, "resume_run", fake)
    return seen


def _wait(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.05)


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
    companies = [CompanyRef(company_id="aapl", name="Apple Inc"), CompanyRef(company_id="msft", name="Microsoft Corporation")]
    run_store.save_companies("extraction_r", companies)
    run_dir = run_store.run_dir("extraction_r")
    (run_dir / "start_request.json").write_text(json.dumps({"profile": "custom", "companies": [c.model_dump(mode="json") for c in companies]}))
    (run_dir / "only_documents.json").write_text(json.dumps({"aapl": ["old"], "msft": ["m"]}))
    run_store.append_result("extraction_r", {"_key": "msft", "company_id": "msft", "name": "Microsoft Corporation", "fields": []})
    run_store.append_error("extraction_r", {"key": "aapl", "error": "No text could be read from old.pdf", "document_problem": True})
    FlowStore(settings.runs_dir / "_flows").update(fid, lambda f: (setattr(f, "run_id", "extraction_r"), setattr(f, "step", 4)))
    return fid


def test_retry_launches_a_job_that_reruns_one_company_on_the_current_kept_files(client, flow, resumed, run_store):
    r = client.post(f"/api/argus/flows/{flow}/companies/aapl/retry")  # the real LocalJobLauncher: needs a running loop
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"  # step 4 keeps polling until the job has run
    _wait(lambda: resumed["calls"])
    assert resumed["calls"] == [["aapl"]]
    assert resumed["errors"] == []  # cleared once the job held the run (AC-38: the row leaves Failed)
    assert resumed["only"]["msft"] == ["m"] and resumed["only"]["aapl"] != ["old"] and len(resumed["only"]["aapl"]) == 1


def test_a_second_retry_before_the_job_runs_is_refused(client, flow, resumed, run_store):
    resumed["delay"] = 1.0
    assert client.post(f"/api/argus/flows/{flow}/companies/aapl/retry").status_code == 200
    assert client.post(f"/api/argus/flows/{flow}/companies/aapl/retry").status_code == 409
    _wait(lambda: resumed["calls"])
    assert resumed["calls"] == [["aapl"]]


def test_a_job_that_fails_before_running_puts_the_error_back(client, flow, resumed, run_store):
    resumed["fail"] = True
    assert client.post(f"/api/argus/flows/{flow}/companies/aapl/retry").status_code == 200
    _wait(lambda: run_store.load_manifest("extraction_r").status not in ("pending", "running"))
    assert [e["error"] for e in run_store.read_errors("extraction_r")] == ["No text could be read from old.pdf"]
    rows = {c["company_id"]: c["status"] for c in client.get(f"/api/argus/flows/{flow}/progress").json()["companies"]}
    assert rows["aapl"] == "Failed"  # never stranded as Stopped; Retry works again
    resumed["fail"] = False
    assert client.post(f"/api/argus/flows/{flow}/companies/aapl/retry").status_code == 200


def test_retry_refuses_a_running_run_and_a_company_that_did_not_fail(client, flow, resumed, run_store):
    assert client.post(f"/api/argus/flows/{flow}/companies/msft/retry").status_code == 400
    m = run_store.load_manifest("extraction_r")
    m.status = JobStatus.RUNNING
    run_store.save_manifest(m)
    assert client.post(f"/api/argus/flows/{flow}/companies/aapl/retry").status_code == 409
    assert resumed["calls"] == []


async def test_resuming_one_company_runs_only_it_through_the_real_batch(tmp_path, pg, monkeypatch):
    """A real financials resume: run_company_batch must not swap the one company for the run's stored list."""
    from arp.extraction import financials_pipeline
    from arp.extraction.financials_pipeline import create_financials_extraction_run
    from arp.ingestion.registry import DocumentSourceRegistry
    from arp.orchestration.jobs import resume_run

    settings = _settings(tmp_path)
    store = RunStore(pg, settings.runs_dir)
    run_id = create_financials_extraction_run(COMPANIES[:3], settings, store)
    for c in ("c2", "c3"):  # c1's row was cleared by Retry
        store.append_error(run_id, {"key": c, "error": "boom"})
    JobManager(store).record_progress(run_id, failed_delta=3)
    JobManager(store).finish_run(run_id)
    calls: list[str] = []

    async def prepare(company, **_):
        return company

    async def extract(company, **_):
        calls.append(company.company_id)
        raise RuntimeError("still broken")

    monkeypatch.setattr(financials_pipeline, "prepare_company", prepare)
    monkeypatch.setattr(financials_pipeline, "_extract_company_financials", extract)
    await resume_run(run_id, settings=settings, run_store=store, registry=DocumentSourceRegistry([]),
                     llm=object(), verifier_llm=object(), company_ids=["c1"])
    assert calls == ["c1"]
    m = store.load_manifest(run_id)
    assert (m.completed_count, m.failed_count) == (0, 3)  # c2 and c3 still failed, c1 failed again: not 5
