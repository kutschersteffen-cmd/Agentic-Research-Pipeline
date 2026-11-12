"""Argus step 2, showcase fixes: an upload that passes its check is kept at once, a removed file can be uploaded
again, and the stored check follows the company's name (spec showcase-argus-fixes, items 9, 11 and 12)."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import get_edgar_source, settings_dep
from arp.api.main import app
from arp.argus import documents
from arp.config import Settings
from arp.discovery.change_detector import ChangeDetector
from arp.discovery.doc_check import DocCheck
from arp.schemas.common import CompanyRef
from arp.schemas.discovery import DiscoveredDocument
from tests.pdf_fixtures import FILLER, make_pdf


@pytest.fixture
def settings(tmp_path, pg):
    return Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache",
                    documents_dir=tmp_path / "docs", discovery_state_dir=tmp_path / "state", postgres_dsn=pg)


@pytest.fixture
def client(settings):
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[get_edgar_source] = lambda: None  # no row here has a ticker
    yield TestClient(app)
    app.dependency_overrides.pop(settings_dep, None)
    app.dependency_overrides.pop(get_edgar_source, None)


@pytest.fixture
def flow(client):
    """A flow for 2025 with Apple; `key` is Apple's company key."""
    fid = client.post("/api/argus/flows").json()["flow_id"]
    key = client.post(f"/api/argus/flows/{fid}/companies", json={"company": {"name": "Apple"}}).json()["companies"][0]["company_id"]
    assert client.patch(f"/api/argus/flows/{fid}", json={"reporting_year": 2025}).status_code == 200
    return fid, key


def pdf(tmp_path, title):
    return make_pdf(tmp_path / "source.pdf", [title, FILLER], n_pages=2).read_bytes()


def up(client, fid, key, name, data):
    r = client.post(f"/api/argus/flows/{fid}/documents/upload", data={"company_id": key, "doc_type": "10-K"},
                    files={"file": (name, data, "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


def decide(client, fid, file_key, state):
    assert client.post(f"/api/argus/flows/{fid}/files", json={"keys": [file_key], "state": state}).status_code == 200


def states(flow):
    return {f["filename"]: f["state"] for f in flow["files"]}


def test_an_upload_that_passes_is_kept_at_once(client, flow, tmp_path):  # AC-35
    fid, key = flow
    assert states(up(client, fid, key, "ar.pdf", pdf(tmp_path, "Apple Annual Report 2025"))) == {"ar.pdf": "kept"}
    assert client.get(f"/api/argus/flows/{fid}").json()["decisions"] == {f"{key}/10-K/ar.pdf": "kept"}


def test_an_upload_that_fails_stays_undecided(client, flow, tmp_path):  # AC-36
    fid, key = flow
    assert states(up(client, fid, key, "ms.pdf", pdf(tmp_path, "Microsoft Annual Report 2025"))) == {"ms.pdf": None}


def test_uploading_a_removed_file_again_keeps_it(client, flow, tmp_path):  # AC-37, AC-38
    fid, key = flow
    data = pdf(tmp_path, "Apple Annual Report 2025")
    up(client, fid, key, "ar.pdf", data)
    decide(client, fid, f"{key}/10-K/ar.pdf", "removed")
    again = up(client, fid, key, "ar.pdf", data)
    assert states(again) == {"ar.pdf": "kept"} and again["skipped_uploads"] == []


def test_a_failing_file_uploaded_again_is_left_undecided(client, flow, tmp_path):  # AC-143
    fid, key = flow
    data = pdf(tmp_path, "Microsoft Annual Report 2025")
    up(client, fid, key, "ms.pdf", data)
    decide(client, fid, f"{key}/10-K/ms.pdf", "kept")  # kept by hand although it fails
    decide(client, fid, f"{key}/10-K/ms.pdf", "removed")
    again = up(client, fid, key, "ms.pdf", data)
    assert states(again) == {"ms.pdf": None} and again["skipped_uploads"] == []


def test_a_duplicate_of_a_kept_file_is_still_skipped(client, flow, tmp_path):  # AC-39
    fid, key = flow
    data = pdf(tmp_path, "Apple Annual Report 2025")
    up(client, fid, key, "ar.pdf", data)
    again = up(client, fid, key, "copy.pdf", data)
    assert [f["check"] for f in again["files"] if f["duplicate_of"]] == ["Duplicate of ar.pdf, skipped"]
    assert states(again)["ar.pdf"] == "kept"


def test_a_file_a_search_found_stays_undecided(client, flow, tmp_path, settings):  # AC-145
    fid, key = flow
    folder = settings.documents_dir / key / "10-K"
    folder.mkdir(parents=True)
    (folder / "sec.pdf").write_bytes(pdf(tmp_path, "Apple Annual Report 2025"))
    detector = ChangeDetector(state_dir=settings.discovery_state_dir, global_events_path=tmp_path / "events.jsonl")
    asyncio.run(detector.diff_and_record(CompanyRef(company_id=key, name="Apple"), [DiscoveredDocument(
        company_id=key, doc_type="10-K", url="https://www.sec.gov/x.pdf", local_path=str(folder / "sec.pdf"), sha256="x")]))
    found = client.get(f"/api/argus/flows/{fid}").json()["files"][0]
    assert (found["source"], found["passes"], found["state"]) == ("filings", True, None)


def test_the_check_follows_the_companys_name(client, tmp_path):  # AC-40
    fid = client.post("/api/argus/flows").json()["flow_id"]
    key = client.post(f"/api/argus/flows/{fid}/companies", json={"company": {"name": "Appel"}}).json()["companies"][0]["company_id"]
    client.patch(f"/api/argus/flows/{fid}", json={"reporting_year": 2025})
    first = up(client, fid, key, "ar.pdf", pdf(tmp_path, "Apple Annual Report 2025"))
    assert first["files"][0]["check"] == "Company not found in document"
    renamed = client.put(f"/api/argus/flows/{fid}/companies/{key}", json={"name": "Apple"})
    assert renamed.status_code == 200 and renamed.json()["companies"][0]["company_id"] == key
    assert client.get(f"/api/argus/flows/{fid}").json()["files"][0]["check"] == "✓ Apple, 2025"


def test_a_failed_read_is_checked_again(client, flow, tmp_path, monkeypatch):  # AC-41
    fid, key = flow
    with monkeypatch.context() as unreadable:
        unreadable.setattr(documents, "check_document", lambda path, company: DocCheck("no_text", None, None))
        first = up(client, fid, key, "ar.pdf", pdf(tmp_path, "Apple Annual Report 2025"))
    assert first["files"][0]["check"] == "Company not found in document"
    assert client.get(f"/api/argus/flows/{fid}").json()["files"][0]["check"] == "✓ Apple, 2025"
