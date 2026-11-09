"""Argus step 2: each file of the flow's companies is checked, kept or removed in the flow only (spec, Step 2)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import settings_dep
from arp.api.main import app
from arp.config import Settings
from tests.pdf_fixtures import FILLER, make_pdf

LIST = "name,company_id\nApple Inc,aapl\nMicrosoft Corporation,msft\nSAP SE,sap\n"


@pytest.fixture
def settings(tmp_path, pg):
    return Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache",
                    documents_dir=tmp_path / "docs", discovery_state_dir=tmp_path / "state", postgres_dsn=pg)


@pytest.fixture
def client(settings):
    app.dependency_overrides[settings_dep] = lambda: settings
    yield TestClient(app)
    app.dependency_overrides.pop(settings_dep, None)


@pytest.fixture
def fid(client):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    assert client.post(f"/api/argus/flows/{fid}/companies/upload", files={"file": ("u.csv", LIST)}).status_code == 200
    assert client.patch(f"/api/argus/flows/{fid}", json={"reporting_year": 2025}).status_code == 200
    return fid


def pdf(tmp_path: Path, name: str, title: str) -> bytes:
    return make_pdf(tmp_path / name, [title, FILLER], n_pages=2).read_bytes()


def up(client, fid, company_id, name, data, doc_type="10-K"):
    r = client.post(f"/api/argus/flows/{fid}/documents/upload", data={"company_id": company_id, "doc_type": doc_type},
                    files={"file": (name, data, "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


def by_name(flow):
    return {f["filename"]: f for f in flow["files"]}


def test_checks(client, fid, tmp_path):
    up(client, fid, "aapl", "good.pdf", pdf(tmp_path, "a.pdf", "Apple Inc Annual Report 2025"))
    up(client, fid, "aapl", "other.pdf", pdf(tmp_path, "b.pdf", "Microsoft Corporation Annual Report 2025"))
    up(client, fid, "aapl", "2023_report.pdf", pdf(tmp_path, "c.pdf", "Apple Inc Annual Report 2023"))
    flow = up(client, fid, "aapl", "noyear.pdf", pdf(tmp_path, "d.pdf", "Apple Inc Annual Report"))
    files = by_name(flow)
    assert (files["good.pdf"]["check"], files["good.pdf"]["passes"]) == ("✓ Apple Inc, 2025", True)
    assert (files["other.pdf"]["check"], files["other.pdf"]["passes"]) == ("Company not found in document", False)  # AC-20
    assert files["2023_report.pdf"]["check"] == "Year 2023, expected 2025"  # AC-21
    assert files["noyear.pdf"]["check"] == "Year unclear"
    assert files["good.pdf"]["source"] == "upload"
    assert files["good.pdf"]["page_url"] == "/api/documents/aapl/10-K/good.pdf/pages/1"


def test_duplicate_upload_is_skipped(client, fid, tmp_path, settings):
    data = pdf(tmp_path, "a.pdf", "Apple Inc Annual Report 2025")
    up(client, fid, "aapl", "ar.pdf", data)
    flow = up(client, fid, "aapl", "ar-copy.pdf", data)
    assert [p.name for p in (settings.documents_dir / "aapl").glob("*/*")] == ["ar.pdf"]  # AC-24
    assert by_name(flow)["ar-copy.pdf"]["check"] == "Duplicate of ar.pdf, skipped"


def test_remove_one_keeps_the_file_on_the_company(client, fid, tmp_path, settings):
    for cid, name in (("aapl", "Apple Inc"), ("msft", "Microsoft Corporation"), ("sap", "SAP SE")):
        up(client, fid, cid, f"{cid}.pdf", pdf(tmp_path, f"{cid}.pdf", f"{name} Annual Report 2025"))
    before = client.post(f"/api/argus/flows/{fid}/files", json={"all_that_pass": True}).json()["rows"]
    r = client.post(f"/api/argus/flows/{fid}/files", json={"keys": ["sap/10-K/sap.pdf"], "state": "removed"})
    assert r.status_code == 200
    flow = client.get(f"/api/argus/flows/{fid}").json()  # AC-18: after a reload
    assert {f["filename"]: f["state"] for f in flow["files"]} == {"aapl.pdf": "kept", "msft.pdf": "kept", "sap.pdf": "removed"}
    assert (settings.documents_dir / "sap" / "10-K" / "sap.pdf").is_file()
    assert flow["rows"] == before  # step 1's Documents on file is unchanged


def test_keep_all_that_pass_and_remove_all(client, fid, tmp_path):
    for i in range(7):
        up(client, fid, "aapl", f"ok{i}.pdf", pdf(tmp_path, f"ok{i}.pdf", f"Apple Inc Annual Report 2025 part {i}"))
    up(client, fid, "aapl", "bad1.pdf", pdf(tmp_path, "bad1.pdf", "Microsoft Corporation Annual Report 2025"))
    up(client, fid, "aapl", "bad2.pdf", pdf(tmp_path, "bad2.pdf", "Apple Inc Annual Report 2021"))
    flow = client.post(f"/api/argus/flows/{fid}/files", json={"all_that_pass": True}).json()  # AC-19
    states = [f["state"] for f in flow["files"]]
    assert states.count("kept") == 7 and states.count(None) == 2
    flow = client.post(f"/api/argus/flows/{fid}/files", json={"all": True, "state": "removed"}).json()  # AC-74
    assert [f["state"] for f in flow["files"]] == ["removed"] * 9


def test_find_needs_a_find_source_and_starts_one_run(client, fid, monkeypatch):
    from arp.api.routers import argus as router

    started = []

    async def fake(run_id, companies, **kw):
        started.append((run_id, len(companies), kw["web"]))

    monkeypatch.setattr(router, "execute_discovery_run", fake)
    assert client.post(f"/api/argus/flows/{fid}/documents/find").status_code == 400
    client.patch(f"/api/argus/flows/{fid}", json={"source": "filings"})
    flow = client.post(f"/api/argus/flows/{fid}/documents/find").json()
    assert started == [(flow["discovery_run_id"], 3, False)]
    assert flow["discovery"]["run_id"] == flow["discovery_run_id"]


def test_upload_for_a_company_outside_the_flow_or_unknown_flow(client, fid, tmp_path):
    data = pdf(tmp_path, "a.pdf", "Apple Inc Annual Report 2025")
    r = client.post(f"/api/argus/flows/{fid}/documents/upload", data={"company_id": "zzz", "doc_type": "10-K"},
                    files={"file": ("a.pdf", data)})
    assert r.status_code == 400
    assert client.post("/api/argus/flows/nope/files", json={"all": True, "state": "removed"}).status_code == 404


def test_step_only_moves_forward(client, fid):
    assert client.patch(f"/api/argus/flows/{fid}", json={"step": 3}).json()["step"] == 3
    assert client.patch(f"/api/argus/flows/{fid}", json={"step": 2}).json()["step"] == 3


def test_files_found_on_websites_or_filings_say_so(client, fid, tmp_path, settings):
    import asyncio

    from arp.discovery.change_detector import ChangeDetector
    from arp.schemas.common import CompanyRef
    from arp.schemas.discovery import DiscoveredDocument

    folder = settings.documents_dir / "aapl" / "10-K"
    folder.mkdir(parents=True)
    urls = {"web.pdf": "https://investor.apple.com/ar.pdf", "sec.pdf": "https://www.sec.gov/x.pdf",
            "fake.pdf": "https://notsec.gov.example.com/x.pdf"}
    for name in urls:
        (folder / name).write_bytes(pdf(tmp_path, name, "Apple Inc Annual Report 2025"))
    detector = ChangeDetector(state_dir=settings.discovery_state_dir, global_events_path=tmp_path / "events.jsonl")
    asyncio.run(detector.diff_and_record(CompanyRef(company_id="aapl", name="Apple Inc"), [
        DiscoveredDocument(company_id="aapl", doc_type="10-K", url=u, local_path=str(folder / n), sha256=n) for n, u in urls.items()]))
    files = by_name(client.get(f"/api/argus/flows/{fid}").json())
    assert {n: files[n]["source"] for n in urls} == {"web.pdf": "web", "sec.pdf": "filings", "fake.pdf": "web"}
