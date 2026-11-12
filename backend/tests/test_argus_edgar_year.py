"""showcase-stewardship-fixes AC-40..AC-44: an EDGAR filing's year is the year of its period of report."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.ingestion import edgar as edgar_module
from arp.ingestion.edgar import EdgarDocumentSource
from arp.schemas.common import CompanyRef
from arp.storage.document_store import DocumentContentStore
from tests.test_edgar_cache import _FailingClient, _write_submissions_cache


@pytest.fixture
def client(tmp_path, pg):
    settings = Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache",
                        documents_dir=tmp_path / "docs", discovery_state_dir=tmp_path / "state", postgres_dsn=pg)
    app.dependency_overrides[settings_dep] = lambda: settings
    yield TestClient(app)
    app.dependency_overrides.pop(settings_dep, None)


def found(client, tmp_path, monkeypatch, pg, form, filed, report=None):
    """A flow for Acme Corp (expected year 2025) and one filing of it found on EDGAR."""
    fid = client.post("/api/argus/flows").json()["flow_id"]
    client.post(f"/api/argus/flows/{fid}/companies/upload", files={"file": ("u.csv", "name,company_id\nAcme Corp,acme\n")})
    client.patch(f"/api/argus/flows/{fid}", json={"reporting_year": 2025})
    recent = {"form": [form], "accessionNumber": ["0000000001-26-000001"], "primaryDocument": ["a.htm"],
              "filingDate": [filed], "acceptanceDateTime": [f"{filed}T16:30:12.000Z"]}
    if report:
        recent["reportDate"] = [report]
    _write_submissions_cache(tmp_path / "edgar", "0000000001", {"filings": {"recent": recent}})

    async def text(self, client, url):
        return "Acme Corp annual report", b"bytes"

    monkeypatch.setattr(EdgarDocumentSource, "_get_and_extract_text", text)
    monkeypatch.setattr(edgar_module.httpx, "AsyncClient", lambda *a, **k: _FailingClient())
    source = EdgarDocumentSource(user_agent="t t@example.com", cache_dir=tmp_path / "edgar",
                                 content_store=DocumentContentStore(tmp_path / "store", dsn=pg))
    assert asyncio.run(source.fetch(CompanyRef(company_id="acme", name="Acme Corp", cik="1")))
    [f] = client.get(f"/api/argus/flows/{fid}").json()["files"]
    return fid, f


def test_10k_year_is_the_period_of_report(client, tmp_path, monkeypatch, pg):  # AC-40, AC-41, AC-42
    fid, f = found(client, tmp_path, monkeypatch, pg, "10-K", "2026-02-14", "2025-12-31")
    assert (f["year"], f["passes"], f["check"]) == (2025, True, "✓ Acme Corp, 2025")
    [kept] = client.post(f"/api/argus/flows/{fid}/files", json={"all_that_pass": True}).json()["files"]
    assert kept["state"] == "kept"


def test_20f_year_is_the_period_of_report(client, tmp_path, monkeypatch, pg):  # AC-43
    _, f = found(client, tmp_path, monkeypatch, pg, "20-F", "2026-04-20", "2025-12-31")
    assert f["year"] == 2025


def test_without_report_date_the_filing_date_counts(client, tmp_path, monkeypatch, pg):  # AC-44 (must not change)
    _, f = found(client, tmp_path, monkeypatch, pg, "10-K", "2026-02-14")
    assert (f["year"], f["check"]) == (2026, "Year 2026, expected 2025")
