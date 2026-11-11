"""Argus step 3's repeat rule: warn when a company would be extracted again from the same files with the same
schema version; count the files added since (spec, The repeat rule)."""

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_run_store, settings_dep
from arp.api.main import app
from arp.argus.repeat import classify
from arp.config import Settings
from arp.schemas.common import RunManifest
from arp.storage.run_store import RunStore
from tests.pdf_fixtures import FILLER, make_pdf

V2 = "sch_x:v2"


def test_classify():
    assert classify(V2, V2, {"a", "b"}, {"a", "b"}) == ("same", 0)  # AC-32
    assert classify(V2, V2, {"a", "b"}, {"a", "c"}) == (None, 0)  # AC-33: a file changed
    assert classify(V2, V2, {"a"}, {"a", "b"}) == ("added", 1)  # AC-34
    assert classify(V2, V2, {"a"}, {"a", "b", "c"}) == ("added", 2)
    assert classify("sch_x:v3", V2, {"a"}, {"a"}) == (None, 0)  # AC-35: another version
    assert classify(V2, None, set(), {"a"}) == (None, 0)  # no earlier run
    assert classify(V2, V2, {"a", "b"}, {"a"}) == (None, 0)  # a file removed
    assert classify(V2, V2, set(), {"a"}) == (None, 0)  # an earlier run that recorded no documents


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


def _upload(client, fid, tmp_path, name, title):
    data = make_pdf(tmp_path / name, [title, FILLER], n_pages=2).read_bytes()
    r = client.post(f"/api/argus/flows/{fid}/documents/upload", data={"company_id": "aapl", "doc_type": "10-K"},
                    files={"file": (name, data, "application/pdf")})
    assert r.status_code == 200, r.text
    return hashlib.sha256(data).hexdigest()


def test_repeat_rows_in_the_flow(client, run_store, tmp_path):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    client.post(f"/api/argus/flows/{fid}/companies/upload", files={"file": ("u.csv", "name,company_id\nApple Inc,aapl\n")})
    client.patch(f"/api/argus/flows/{fid}", json={"reporting_year": 2025, "step": 3})
    key = _upload(client, fid, tmp_path, "a.pdf", "Apple Inc Annual Report 2025")
    client.post(f"/api/argus/flows/{fid}/files", json={"all_that_pass": True})
    run_store.save_manifest(RunManifest(run_id="extraction_r1", run_type="extraction", created_at="2026-10-01T00:00:00Z",
                                        company_count=1, params={"schema_name": "S", "schema_id": "sch_x", "schema_version": V2}))
    run_store.append_result("extraction_r1", {"company_id": "aapl", "name": "Apple Inc", "issuer_key": "k", "fields": [],
                                              "documents": [{"doc_id": "d", "content_key": key}]})

    flow = client.patch(f"/api/argus/flows/{fid}", json={"schema_choice": {"kind": "schema", "schema_id": "sch_x", "version": 2}}).json()
    assert [(r["company_id"], r["kind"], r["date"], r["run_id"]) for r in flow["repeat_rows"]] == [("aapl", "same", "2026-10-01", "extraction_r1")]

    _upload(client, fid, tmp_path, "b.pdf", "Apple Inc Sustainability Report 2025")
    flow = client.post(f"/api/argus/flows/{fid}/files", json={"all_that_pass": True}).json()
    assert [(r["kind"], r["added"]) for r in flow["repeat_rows"]] == [("added", 1)]  # AC-34

    flow = client.patch(f"/api/argus/flows/{fid}", json={"schema_choice": {"kind": "schema", "schema_id": "sch_x", "version": 3}}).json()
    assert flow["repeat_rows"] == []  # AC-35


def _flow_with_apple_file(client, tmp_path):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    client.post(f"/api/argus/flows/{fid}/companies/upload", files={"file": ("u.csv", "name,company_id\nApple Inc,aapl\n")})
    client.patch(f"/api/argus/flows/{fid}", json={"reporting_year": 2025, "step": 3})
    key = _upload(client, fid, tmp_path, "a.pdf", "Apple Inc Annual Report 2025")
    client.post(f"/api/argus/flows/{fid}/files", json={"all_that_pass": True})
    return fid, key


def test_a_profile_run_started_from_argus_warns(client, run_store, tmp_path):
    from arp.ingestion.registry import ONLY_DOCUMENTS

    fid, key = _flow_with_apple_file(client, tmp_path)
    run_store.save_manifest(RunManifest(run_id="tnfd_r1", run_type="tnfd", created_at="2026-10-02T00:00:00Z", company_count=1))
    run_store.append_result("tnfd_r1", {"company_id": "aapl", "name": "Apple Inc", "issuer_key": "k", "fields": []})  # no documents
    (run_store.run_dir("tnfd_r1") / ONLY_DOCUMENTS).write_text(json.dumps({"aapl": [key]}))
    flow = client.patch(f"/api/argus/flows/{fid}", json={"schema_choice": {"kind": "profile", "profile": "tnfd"}}).json()
    assert [(r["kind"], r["run_id"]) for r in flow["repeat_rows"]] == [("same", "tnfd_r1")]


def test_a_run_with_no_document_record_is_not_listed(client, run_store, tmp_path):
    fid, _ = _flow_with_apple_file(client, tmp_path)
    run_store.save_manifest(RunManifest(run_id="tnfd_r2", run_type="tnfd", created_at="2026-10-02T00:00:00Z", company_count=1))
    run_store.append_result("tnfd_r2", {"company_id": "aapl", "name": "Apple Inc", "issuer_key": "k", "fields": []})
    flow = client.patch(f"/api/argus/flows/{fid}", json={"schema_choice": {"kind": "profile", "profile": "tnfd"}}).json()
    assert flow["repeat_rows"] == []


def test_repeat_rows_wait_for_step_3(client, run_store, tmp_path):
    fid, key = _flow_with_apple_file(client, tmp_path)
    run_store.save_manifest(RunManifest(run_id="extraction_r9", run_type="extraction", created_at="2026-10-01T00:00:00Z",
                                        company_count=1, params={"schema_id": "sch_x", "schema_version": V2}))
    run_store.append_result("extraction_r9", {"company_id": "aapl", "name": "Apple Inc", "issuer_key": "k", "fields": [],
                                              "documents": [{"content_key": key}]})
    client.patch(f"/api/argus/flows/{fid}", json={"schema_choice": {"kind": "schema", "schema_id": "sch_x", "version": 2}})
    flow_path = Path(client.app.dependency_overrides[settings_dep]().runs_dir) / "_flows" / f"{fid}.json"
    data = json.loads(flow_path.read_text())
    data["step"] = 2
    flow_path.write_text(json.dumps(data))
    assert client.get(f"/api/argus/flows/{fid}").json()["repeat_rows"] == []


def test_a_trial_run_is_not_an_earlier_extraction(client, run_store, tmp_path):
    """A trial stores no facts. Listed as "extracted before", it made Start demand a choice, and "Skip, keep
    earlier results" then left the company out of the real run with nothing kept."""
    fid = client.post("/api/argus/flows").json()["flow_id"]
    client.post(f"/api/argus/flows/{fid}/companies/upload", files={"file": ("u.csv", "name,company_id\nApple Inc,aapl\n")})
    client.patch(f"/api/argus/flows/{fid}", json={"reporting_year": 2025, "step": 3})
    key = _upload(client, fid, tmp_path, "a.pdf", "Apple Inc Annual Report 2025")
    client.post(f"/api/argus/flows/{fid}/files", json={"all_that_pass": True})
    run_store.save_manifest(RunManifest(run_id="extraction_trial", run_type="extraction", created_at="2026-10-01T00:00:00Z", company_count=1,
                                        params={"schema_name": "S", "schema_id": "sch_x", "schema_version": V2, "trial": True}))
    run_store.append_result("extraction_trial", {"company_id": "aapl", "name": "Apple Inc", "issuer_key": "k", "fields": [],
                                                 "documents": [{"doc_id": "d", "content_key": key}]})

    flow = client.patch(f"/api/argus/flows/{fid}", json={"schema_choice": {"kind": "schema", "schema_id": "sch_x", "version": 2}}).json()
    assert flow["repeat_rows"] == []
