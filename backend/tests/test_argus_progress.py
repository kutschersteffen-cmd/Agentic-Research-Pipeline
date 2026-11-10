"""Argus step 4: the run's progress per company, in the spec's fixed statuses."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_run_store, settings_dep
from arp.api.main import app
from arp.argus.flows import FlowStore
from arp.argus.progress import company_status, minutes_left
from arp.config import Settings
from arp.orchestration import step_tally
from arp.schemas.common import RunManifest
from arp.storage.run_store import RunStore


@pytest.mark.parametrize("raw, run, steps, expected", [
    ("done", "running", {}, ("Done", 100)),
    ("review", "completed", {}, ("Done", 100)),
    ("failed", "partially_completed", {}, ("Failed", 0)),
    ("waiting", "cancelled", {}, ("Stopped", 0)),
    ("waiting", "partially_completed", {}, ("Stopped", 0)),  # never started and the run is over
    ("waiting", "pending", {}, ("Waiting", 0)),
    ("waiting", "running", {}, ("Waiting", 0)),
    ("waiting", "running", {"parse_index": 1}, ("Reading documents", 25)),
    ("waiting", "running", {"gather_evidence": 4, "extract": 2}, ("Extracting", 50)),
    ("waiting", "running", {"gather_evidence": 4, "extract": 4, "verify": 1}, ("Checking the answers", 75)),
    ("waiting", "running", {"aggregate": 1}, ("Checking the answers", 75)),
])
def test_company_status(raw, run, steps, expected):
    assert company_status(raw, run, steps) == expected


def test_minutes_left():
    start = datetime(2026, 11, 10, 14, 0, tzinfo=UTC)
    assert minutes_left(start, start + timedelta(minutes=6), done=3, total=10) == 14  # 2 min each, 7 to go
    assert minutes_left(start, start + timedelta(minutes=5), done=3, total=10) == 12  # rounded up
    assert minutes_left(start, start + timedelta(minutes=5), done=0, total=10) is None  # nothing finished yet
    assert minutes_left(start, start + timedelta(minutes=5), done=10, total=10) == 0


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


def _run(run_store, status, created_at="2026-11-10T14:02:00+00:00", **counts):
    run_store.save_manifest(RunManifest(run_id="extraction_p", run_type="extraction", created_at=created_at, status=status,
                                        company_count=4, estimated_cost_usd=1.234, **counts))
    companies = [{"company_id": c, "name": c.upper()} for c in ("a", "b", "c", "d")]
    (run_store.run_dir("extraction_p") / "start_request.json").write_text(json.dumps({"profile": "custom", "companies": companies}))


def _flow(client, settings, run_id="extraction_p"):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    FlowStore(settings.runs_dir / "_flows").update(fid, lambda f: (setattr(f, "run_id", run_id), setattr(f, "step", 4)))
    return fid


def test_progress_mixes_statuses(client, settings, run_store):
    _run(run_store, "running", completed_count=1, failed_count=1)
    run_store.append_result("extraction_p", {"_key": "a", "company_id": "a", "name": "A", "issuer_key": "a", "fields": [
        {"field_id": "f1", "route": "review"}, {"field_id": "f2", "route": "auto_accept"}]})
    run_store.append_error("extraction_p", {"key": "b", "error": "No text could be read from b.pdf", "document_problem": True})
    step_tally._live["extraction_p"] = step_tally._Tally()
    step_tally._live["extraction_p"].add("c", "extract", 1.0)
    try:
        p = client.get(f"/api/argus/flows/{_flow(client, settings)}/progress").json()
    finally:
        step_tally._live.pop("extraction_p", None)
    assert (p["started_at"], p["done"], p["total"], p["cost_usd"], p["status"]) == ("2026-11-10T14:02:00+00:00", 2, 4, 1.234, "running")
    rows = {r["company_id"]: r for r in p["companies"]}
    assert (rows["a"]["status"], rows["a"]["needs_you"]) == ("Done", 1)
    assert (rows["b"]["status"], rows["b"]["reason"], rows["b"]["document_problem"]) == (
        "Failed", "No text could be read from b.pdf", True)
    assert rows["c"]["status"] == "Extracting" and rows["d"]["status"] == "Waiting"


def test_progress_after_stop_and_without_a_live_tally(client, settings, run_store):
    _run(run_store, "cancelled", completed_count=1)  # the API restarted: no live counts, nothing on disk
    run_store.append_result("extraction_p", {"_key": "a", "company_id": "a", "name": "A", "issuer_key": "a", "fields": []})
    p = client.get(f"/api/argus/flows/{_flow(client, settings)}/progress").json()
    assert [r["status"] for r in p["companies"]] == ["Done", "Stopped", "Stopped", "Stopped"]  # AC-72


def test_progress_needs_a_run(client, settings):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    assert client.get(f"/api/argus/flows/{fid}/progress").status_code == 404
    assert client.get("/api/argus/flows/nope/progress").status_code == 404
