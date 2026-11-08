import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.main import app
from arp.api.routers import authority_taxonomy as authority_router
from arp.research.authority_taxonomy import run
from arp.research.authority_taxonomy.discovery import Candidate
from arp.research.authority_taxonomy.extract import SourceExtraction
from arp.storage.run_store import LegacyRunStore
from arp.storage.taxonomy_store import TaxonomyStore
from tests.test_authority_taxonomy_consolidate import _act, _fake, _settings

BASE = "/api/authority-taxonomy/runs"


@pytest.fixture
def client(monkeypatch, tmp_path):
    async def fake_discover(theme_name, theme_key, guidance, **kw):
        return [Candidate(url=f"https://{c}.org", title=c, source_type="agency_report", summary="s", reason="r",
                          fetchable=True, covers=[], from_library=False) for c in "abc"]

    async def fake_fetch(url, user_agent, timeout=20.0, max_chars=0):
        return "text"

    async def fake_extract(url, text, **kw):
        return SourceExtraction(url=url, activities=[_act("Stacks", url)])

    monkeypatch.setattr(run, "discover_candidates", fake_discover)
    monkeypatch.setattr(run, "fetch_source_text", fake_fetch)
    monkeypatch.setattr(run, "extract_source", fake_extract)
    store, tax, settings = LegacyRunStore(tmp_path / "runs"), TaxonomyStore(tmp_path / "tax"), _settings(tmp_path)
    app.dependency_overrides.update({
        deps.get_run_store: lambda: store, deps.get_taxonomy_store: lambda: tax, deps.settings_dep: lambda: settings,
        deps.get_llm_client: lambda: _fake(10), deps.get_web_search_client: lambda: None,
    })
    jobs: list = []

    class Launcher:  # holds background steps until a test runs them with _drain
        def launch(self, run_id, job, *, run_store=None):
            jobs.append(job)

    monkeypatch.setattr(authority_router, "get_job_launcher", Launcher)
    c = TestClient(app)
    c.settings, c.jobs = settings, jobs
    yield c
    app.dependency_overrides.clear()


def _drain(client):
    while client.jobs:
        asyncio.run(client.jobs.pop(0)())


def _start(client):
    res = client.post(BASE, json={"theme_name": "Hydrogen"})
    _drain(client)
    return res


def _reviewed(client):
    rid = _start(client).json()["id"]
    assert client.post(f"{BASE}/{rid}/sources", json={"urls": ["https://a.org"], "files": []}).status_code == 200
    _drain(client)
    return rid


def test_start_returns_201(client):
    res = _start(client)
    assert res.status_code == 201
    assert res.json()["stage"] == "discovering"


def test_get_run_candidates(client):
    rid = _start(client).json()["id"]
    assert len(client.get(f"{BASE}/{rid}").json()["candidates"]) == 3


def test_put_draft_200(client):
    rid = _reviewed(client)
    draft = client.get(f"{BASE}/{rid}/draft").json()
    draft["activities"][0]["name"] = "N"
    assert client.put(f"{BASE}/{rid}/draft", json=draft).status_code == 200
    assert client.get(f"{BASE}/{rid}/draft").json()["activities"][0]["name"] == "N"
    draft["activities"][0]["citations"] = []
    assert client.put(f"{BASE}/{rid}/draft", json=draft).status_code == 422


def test_accept_201(client):
    rid = _reviewed(client)
    res = client.post(f"{BASE}/{rid}/accept")
    assert res.status_code == 201
    tid = res.json()["taxonomy_id"]
    assert tid
    assert client.get(f"{BASE}/{rid}").json()["stage"] == "accepted"
    draft = client.get(f"{BASE}/{rid}/draft").json()
    assert draft["activities"][0]["name"] == "Stacks"


def test_accept_shows_in_cli(client, monkeypatch):
    from typer.testing import CliRunner

    from arp.cli import taxonomy as cli

    rid = _reviewed(client)
    draft = client.get(f"{BASE}/{rid}/draft").json()
    draft["activities"][0]["name"] = "Edited stacks"
    assert client.put(f"{BASE}/{rid}/draft", json=draft).status_code == 200
    tid = client.post(f"{BASE}/{rid}/accept").json()["taxonomy_id"]
    monkeypatch.setattr(cli, "_taxonomy_store", app.dependency_overrides[deps.get_taxonomy_store])
    out = CliRunner().invoke(cli.taxonomy_app, ["show", tid])
    assert out.exit_code == 0, out.output
    assert all(s in out.output for s in ["Edited stacks", '"version": 1', "authority_source", "draft"])


def test_accept_409(client):
    rid = _start(client).json()["id"]
    res = client.post(f"{BASE}/{rid}/accept")
    assert (res.status_code, res.json()) == (409, {"detail": "run is at stage awaiting_sources"})


def test_delete_204(client):
    rid = _start(client).json()["id"]
    assert client.delete(f"{BASE}/{rid}").status_code == 204
    assert client.get(f"{BASE}/{rid}").json()["stage"] == "cancelled"


def test_delete_at_review_204(client):
    rid = _reviewed(client)
    assert client.delete(f"{BASE}/{rid}").status_code == 204
    assert client.get(f"{BASE}/{rid}").json()["stage"] == "cancelled"


def test_select_no_sources_422(client):
    rid = _start(client).json()["id"]
    assert client.post(f"{BASE}/{rid}/sources", json={"urls": [], "files": []}).status_code == 422


def test_unknown_run_404(client):
    assert client.get(f"{BASE}/nope").status_code == 404


def test_files_confined(client, tmp_path):
    rid = _start(client).json()["id"]
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ok.txt").write_text("text")
    (tmp_path / "secret.txt").write_text("x")
    for bad in ["/etc/passwd", str(docs / ".." / "secret.txt"), str(docs)]:
        res = client.post(f"{BASE}/{rid}/sources", json={"urls": [], "files": [bad]})
        assert res.status_code == 422 and res.json()["detail"].startswith("file not allowed")
    res = client.post(f"{BASE}/{rid}/sources", json={"urls": [], "files": [str(docs / "ok.txt")]})
    assert res.status_code == 200


def test_start_returns_before_discovery(client):
    res = client.post(BASE, json={"theme_name": "Hydrogen"})
    assert (res.status_code, res.json()["stage"]) == (201, "discovering")
    state = client.get(f"{BASE}/{res.json()['id']}").json()
    assert (state["stage"], state["error"]) == ("discovering", None)


def test_sources_returns_extracting(client):
    rid = _start(client).json()["id"]
    res = client.post(f"{BASE}/{rid}/sources", json={"urls": ["https://a.org"], "files": []})
    assert (res.status_code, res.json()["stage"]) == (200, "extracting")


def test_sources_twice_409(client):
    rid = _start(client).json()["id"]
    body = {"urls": ["https://a.org"], "files": []}
    assert client.post(f"{BASE}/{rid}/sources", json=body).status_code == 200
    res = client.post(f"{BASE}/{rid}/sources", json=body)
    assert (res.status_code, res.json()["detail"]) == (409, "run is at stage extracting")


def test_sources_bad_file_422_keeps_stage(client):
    rid = _start(client).json()["id"]
    res = client.post(f"{BASE}/{rid}/sources", json={"urls": [], "files": ["/etc/passwd"]})
    assert res.status_code == 422
    assert client.get(f"{BASE}/{rid}").json()["stage"] == "awaiting_sources"


def _upload(client, name, data=b"hello"):
    return client.post(f"{BASE.rsplit('/', 1)[0]}/uploads", files={"file": (name, data)})


def test_upload_txt(client):
    res = _upload(client, "note.txt")
    path = res.json()["path"]
    assert res.status_code == 200
    assert path == str(client.settings.documents_dir / "_authority" / "note.txt")
    assert Path(path).read_bytes() == b"hello"


def test_upload_twice_suffix(client):
    first, second = _upload(client, "note.txt", b"1"), _upload(client, "note.txt", b"2")
    assert second.json()["path"].endswith("note-2.txt")
    assert Path(first.json()["path"]).read_bytes() == b"1"


def test_upload_docx_422(client):
    res = _upload(client, "note.docx")
    assert (res.status_code, res.json()["detail"]) == (422, "unsupported file type")
    assert not (client.settings.documents_dir / "_authority").exists()


def test_upload_path_accepted_by_sources(client):
    rid = _start(client).json()["id"]
    path = _upload(client, "note.md").json()["path"]
    assert client.post(f"{BASE}/{rid}/sources", json={"urls": [], "files": [path]}).status_code == 200


def test_upload_traversal_name(client):
    assert _upload(client, "../x.txt").status_code == 422
    assert _upload(client, "..").status_code == 422
    assert not (client.settings.documents_dir / "_authority").exists()


def test_upload_too_large_413(client):
    client.settings.max_upload_bytes = 4
    assert _upload(client, "a.txt", b"12345").status_code == 413


def test_upload_bad_name_422(client):
    res = _upload(client, "")
    assert res.status_code in (422,)
    assert not (client.settings.documents_dir / "_authority").exists()


def test_put_draft_does_not_create_taxonomy(client):
    rid = _reviewed(client)
    before = len(app.dependency_overrides[deps.get_taxonomy_store]().list_all())
    draft = client.get(f"{BASE}/{rid}/draft").json()
    assert client.put(f"{BASE}/{rid}/draft", json=draft).status_code == 200
    assert len(app.dependency_overrides[deps.get_taxonomy_store]().list_all()) == before


def test_documents_upload_unchanged(client):
    res = client.post("/api/documents/upload", data={"company_id": "acme", "doc_type": "other"}, files={"file": ("a.txt", b"x")})
    assert res.json()["path"] == str(client.settings.documents_dir / "acme" / "other" / "a.txt")
