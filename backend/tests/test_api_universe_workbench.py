from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.auth import authorize, current_user
from arp.api.routers import universe_workbench as wb
from arp.config import Settings
from arp.schemas.issuer import IdentifierMap
from arp.storage.document_store import DocumentContentStore
from arp.storage.identifier_map import IdentifierMapStore
from tests.conftest import PRINCIPAL


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        runs_dir=tmp_path / "runs",
        xbrl_dir=tmp_path / "xbrl",
        documents_dir=tmp_path / "docs",
        identifier_map_path=tmp_path / "idmap.jsonl",
    )
    (settings.runs_dir / "_universes").mkdir(parents=True)
    IdentifierMapStore(settings.identifier_map_path).add(
        IdentifierMap(issuer_key="INTERNAL:1", scheme="CIK", value="0000320193")
    )
    app = FastAPI()
    app.include_router(wb.router)
    app.dependency_overrides[deps.settings_dep] = lambda: settings
    app.dependency_overrides[deps.get_document_content_store] = lambda: DocumentContentStore(tmp_path / "store")
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    return TestClient(app), settings


def test_workbench_with_companies(env):
    client, _ = env
    r = client.post("/api/universe/workbench", json={"companies": [
        {"company_id": "us", "name": "US Co", "cik": "320193"},
        {"company_id": "eu", "name": "EU Co", "country": "DE"},
        {"company_id": "nx", "name": "Nowhere"},
    ]})
    assert r.status_code == 200
    body = r.json()
    rows = {x["company"]["company_id"]: x for x in body["rows"]}
    assert rows["us"]["mapping"]["status"] == "mapped"
    assert rows["us"]["route"]["market"] == "sec"
    assert rows["eu"]["route"]["market"] == "esef"
    assert rows["eu"]["mapping"]["status"] == "no_identifier"
    assert rows["nx"]["route"]["status"] == "unrouted"
    assert rows["us"]["availability"]["documents"]["registered"] == 0
    assert body["counts"]["routes"] == {"sec": 1, "esef": 1, "no_source": 0, "unrouted": 1}
    assert body["counts"]["mapping"] == {"mapped": 1, "ambiguous": 0, "unmapped": 0, "no_identifier": 2}


def test_workbench_with_saved_universe_path(env):
    client, settings = env
    p = settings.runs_dir / "_universes" / "u.json"
    p.write_text(json.dumps([{"company_id": "a", "name": "A", "country": "US"}]))
    r = client.post("/api/universe/workbench", json={"universe_path": str(p)})
    assert r.status_code == 200
    assert r.json()["rows"][0]["route"]["market"] == "sec"


def test_path_outside_universes_is_400(env, tmp_path, monkeypatch, request):
    client, settings = env
    calls = []
    monkeypatch.setattr(wb, "load_company_universe", lambda p: calls.append(p) or [])
    outside = tmp_path / "x.csv"
    outside.write_text("company_id,name\na,A\n")
    link = settings.runs_dir / "_universes" / "link.csv"
    link.symlink_to(outside)
    for path in ("../etc/passwd", str(outside), str(link)):
        r = client.post("/api/universe/workbench", json={"universe_path": path})
        assert r.status_code == 400, path
        assert r.json()["detail"] == "Universe file must be a saved universe."
    assert calls == []


def test_requires_companies_or_path(env):
    client, _ = env
    r = client.post("/api/universe/workbench", json={})
    assert r.status_code == 400
    assert r.json()["detail"] == "Provide either `companies` or `universe_path`."


def test_too_many_companies(env):
    client, _ = env
    cos = [{"company_id": f"c{i}", "name": "n"} for i in range(10_001)]
    assert client.post("/api/universe/workbench", json={"companies": cos}).status_code == 400


def test_duplicate_company_ids_both_rows_returned(env):
    client, _ = env
    r = client.post("/api/universe/workbench", json={"companies": [
        {"company_id": "d", "name": "A", "country": "US"},
        {"company_id": "d", "name": "B", "country": "DE"},
    ]})
    assert [x["route"]["market"] for x in r.json()["rows"]] == ["sec", "esef"]


def test_requires_authorization(tmp_path):
    from arp.api.main import app

    saved = {k: app.dependency_overrides.pop(k, None) for k in (authorize, current_user)}
    try:
        r = TestClient(app).post("/api/universe/workbench", json={"companies": []})
        assert r.status_code == 401
    finally:
        for k, v in saved.items():
            if v is not None:
                app.dependency_overrides[k] = v
