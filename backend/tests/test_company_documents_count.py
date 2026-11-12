"""showcase-stewardship-fixes AC-70, AC-71: the company page counts an uploaded file before a run registers it, once."""

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.storage.document_store import DocumentContentStore

L1 = "5299000ACMEPOWER1065"


@pytest.fixture
def settings(tmp_path, pg):
    return Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache",
                    documents_dir=tmp_path / "docs", discovery_state_dir=tmp_path / "state", postgres_dsn=pg)


@pytest.fixture
def client(settings):
    app.dependency_overrides[settings_dep] = lambda: settings
    yield TestClient(app)
    app.dependency_overrides.pop(settings_dep, None)


def test_upload_counts_once_before_and_after_registration(client, settings, tmp_path, pg):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    flow = client.post(f"/api/argus/flows/{fid}/companies/upload",
                       files={"file": ("u.csv", f"name,lei,isic_code\nAcme Power AG,{L1},3510\n")}).json()
    company = flow["companies"][0]
    e, key = company["entity_id"], company["company_id"]
    assert client.get(f"/api/companies/{e}").json()["documents"] == 0
    r = client.post(f"/api/argus/flows/{fid}/documents/upload", data={"company_id": key, "doc_type": "sustainability_report"},
                    files={"file": ("report.txt", b"Acme Power AG sustainability report 2025", "text/plain")})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/companies/{e}").json()["documents"] == 1  # AC-70
    [path] = (settings.documents_dir / key).glob("*/*")
    DocumentContentStore(tmp_path / "store", dsn=pg).register_document(  # what a run does when it reads the file
        doc_id="doc_acme1", company_id=key, doc_type="sustainability_report", content_key="ck_acme1", title="report.txt",
        local_path=str(path), source_url=None)
    assert client.get(f"/api/companies/{e}").json()["documents"] == 1  # AC-71
