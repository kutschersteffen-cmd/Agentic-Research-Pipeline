import pytest
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.main import app
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
    yield TestClient(app)
    app.dependency_overrides.clear()


def _start(client):
    return client.post(BASE, json={"theme_name": "Hydrogen"})


def _reviewed(client):
    rid = _start(client).json()["id"]
    assert client.post(f"{BASE}/{rid}/sources", json={"urls": ["https://a.org"], "files": []}).status_code == 200
    return rid


def test_start_returns_201(client):
    res = _start(client)
    assert res.status_code == 201
    assert res.json()["stage"] == "awaiting_sources"


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
    assert res.json()["taxonomy_id"]


def test_accept_409(client):
    rid = _start(client).json()["id"]
    res = client.post(f"{BASE}/{rid}/accept")
    assert (res.status_code, res.json()) == (409, {"detail": "run is at stage awaiting_sources"})


def test_delete_204(client):
    rid = _start(client).json()["id"]
    assert client.delete(f"{BASE}/{rid}").status_code == 204
    assert client.get(f"{BASE}/{rid}").json()["stage"] == "cancelled"


def test_select_no_sources_422(client):
    rid = _start(client).json()["id"]
    assert client.post(f"{BASE}/{rid}/sources", json={"urls": [], "files": []}).status_code == 422


def test_unknown_run_404(client):
    assert client.get(f"{BASE}/nope").status_code == 404
