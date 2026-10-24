"""Argus step 2: files uploaded into a flow get a name and year check; Remove only marks them."""

import io

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import settings_dep
from arp.api.main import app
from arp.config import Settings
from tests.pdf_fixtures import make_pdf

APPLE_2025 = ["Apple Inc. Annual Report 2025"]


@pytest.fixture
def settings(tmp_path, pg):
    return Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", cache_dir=tmp_path / "cache",
                    documents_dir=tmp_path / "docs", postgres_dsn=pg)


@pytest.fixture
def client(settings):
    app.dependency_overrides[settings_dep] = lambda: settings
    yield TestClient(app)
    app.dependency_overrides.pop(settings_dep, None)


@pytest.fixture
def flow(client):
    fid = client.post("/api/argus/flows").json()["flow_id"]
    client.post(f"/api/argus/flows/{fid}/companies", json={"company": {"name": "Apple Inc.", "lei": "HWUPKR0MPOU8FGXBT394"}})
    f = client.patch(f"/api/argus/flows/{fid}", json={"reporting_year": 2025}).json()
    client.post(f"/api/argus/flows/{fid}/companies", json={"company": {"name": "Microsoft Corporation", "isin": "US5949181045"}})
    f = client.get(f"/api/argus/flows/{fid}").json()
    return fid, {c["name"].split()[0].lower(): c["company_id"] for c in f["companies"]}


def pdf_bytes(tmp_path, pages):
    return make_pdf(tmp_path / "x.pdf", pages, n_pages=1).read_bytes()


def upload(client, flow, who, name, data, doc_type="10-K", status=200):
    fid, ids = flow
    r = client.post(f"/api/argus/flows/{fid}/documents/upload",
                    data={"company_id": ids.get(who, who), "doc_type": doc_type}, files={"file": (name, data)})
    assert r.status_code == status, r.text
    return r.json()


def test_pdf_naming_apple_and_the_year_passes(client, flow, tmp_path):
    f = upload(client, flow, "apple", "2025_10-K.pdf", pdf_bytes(tmp_path, APPLE_2025))
    [row] = f["files"]
    assert (row["check"], row["passed"], row["state"], row["year"], row["source"]) == ("✓ name, year", True, "kept", 2025, "upload")
    assert f["doc_source"] == "upload"


def test_pdf_naming_only_microsoft(client, flow, tmp_path):
    [row] = upload(client, flow, "apple", "2025_r.pdf", pdf_bytes(tmp_path, ["Microsoft Corporation Annual Report 2025"]))["files"]
    assert (row["check"], row["passed"], row["state"]) == ("Company not found in document", False, None)


def test_wrong_year_then_year_changed(client, flow, tmp_path):
    [row] = upload(client, flow, "apple", "2023_report.pdf", pdf_bytes(tmp_path, ["Apple Inc. Report 2023"]))["files"]
    assert row["check"] == "Year 2023, expected 2025"
    f = client.patch(f"/api/argus/flows/{flow[0]}", json={"reporting_year": 2023}).json()
    assert f["files"][0]["check"] == "✓ name, year"


def test_year_read_from_the_document_and_unclear(client, flow, tmp_path):
    upload(client, flow, "apple", "a.pdf", pdf_bytes(tmp_path, APPLE_2025))
    f = upload(client, flow, "apple", "report.pdf", pdf_bytes(tmp_path, ["Apple Inc. annual report"]))
    assert [(r["year"], r["check"]) for r in f["files"]] == [(2025, "✓ name, year"), (None, "Year unclear")]


def test_same_pdf_twice_is_stored_once(client, flow, tmp_path):
    data = pdf_bytes(tmp_path, APPLE_2025)
    upload(client, flow, "apple", "a.pdf", data)
    f = upload(client, flow, "apple", "a-copy.pdf", data)
    assert [r["check"] for r in f["files"]] == ["✓ name, year", "Duplicate of a.pdf, skipped"]
    assert f["files"][1]["state"] is None
    assert len(client.get(f"/api/documents/{flow[1]['apple']}").json()["documents"]) == 1


def test_a_file_already_on_the_company_joins_the_flow(client, flow, tmp_path):
    data = pdf_bytes(tmp_path, APPLE_2025)
    client.post("/api/documents/upload", data={"company_id": flow[1]["apple"], "doc_type": "10-K"}, files={"file": ("old.pdf", data)})
    [row] = upload(client, flow, "apple", "new.pdf", data)["files"]
    assert (row["file_name"], row["check"]) == ("old.pdf", "✓ name, year")


def test_same_pdf_for_two_companies_is_two_files(client, flow, tmp_path):
    data = pdf_bytes(tmp_path, ["Apple Inc. and Microsoft Corporation 2025"])
    upload(client, flow, "apple", "a.pdf", data)
    f = upload(client, flow, "microsoft", "a.pdf", data)
    assert [(r["company_id"], r["check"]) for r in f["files"]] == [(flow[1]["apple"], "✓ name, year"), (flow[1]["microsoft"], "✓ name, year")]


def test_remove_keeps_the_file_on_disk(client, flow, tmp_path, settings):
    [row] = upload(client, flow, "apple", "a.pdf", pdf_bytes(tmp_path, APPLE_2025))["files"]
    f = client.patch(f"/api/argus/flows/{flow[0]}", json={"decisions": {row["key"]: "removed"}}).json()
    assert f["files"][0]["state"] == "removed"
    assert (settings.documents_dir / row["key"]).is_file()
    assert client.get(f"/api/argus/flows/{flow[0]}").json()["files"][0]["state"] == "removed"


def test_non_pdf_and_foreign_company_are_400(client, flow, tmp_path):
    assert upload(client, flow, "apple", "a.docx", b"x", status=400)["detail"] == "Upload a PDF"
    assert upload(client, flow, "someone-else", "a.pdf", pdf_bytes(tmp_path, APPLE_2025), status=400)["detail"] == "Not in this extraction"


async def test_documents_upload_skips_identical_content(tmp_path):
    from starlette.datastructures import UploadFile

    from arp.api.routers.documents import upload_document
    from arp.schemas.common import DocType

    settings = Settings(documents_dir=tmp_path)
    first = await upload_document("acme", DocType.OTHER, UploadFile(io.BytesIO(b"one"), filename="r.pdf"), settings)
    second = await upload_document("acme", DocType.TRANSITION_PLAN, UploadFile(io.BytesIO(b"one"), filename="s.pdf"), settings)
    assert (second["path"], second["duplicate_of"], first["duplicate_of"]) == (first["path"], "r.pdf", None)
    assert [p.name for p in tmp_path.rglob("*.pdf")] == ["r.pdf"]
