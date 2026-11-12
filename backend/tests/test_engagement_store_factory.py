"""build_engagement_store picks the backend by setting; the API behaves the same on both."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.auth import current_user
from arp.api.routers import engagement
from arp.config import Settings
from arp.storage.engagement_store import EngagementStore
from arp.storage.engagement_store_factory import build_engagement_store
from arp.storage.postgres_engagement_store import PostgresEngagementStore
from tests.conftest import PRINCIPAL


def _client(settings: Settings) -> TestClient:
    store = build_engagement_store(settings)
    app = FastAPI()
    app.include_router(engagement.router)
    app.dependency_overrides[deps.get_engagement_store] = lambda: store
    app.dependency_overrides[current_user] = lambda: PRINCIPAL
    return TestClient(app)


def _strip(x):
    if isinstance(x, dict):
        return {k: _strip(v) for k, v in x.items() if not (k.endswith(("_id", "_at")) or k == "date")}
    if isinstance(x, list):
        return [_strip(v) for v in x]
    return x


def test_default_is_file(tmp_path):
    assert isinstance(build_engagement_store(Settings(engagements_dir=tmp_path)), EngagementStore)


def test_postgres_setting(pg, tmp_path):
    store = build_engagement_store(Settings(engagement_store="postgres", postgres_dsn=pg, engagements_dir=tmp_path))
    assert isinstance(store, PostgresEngagementStore)


def test_postgres_never_writes_files(pg, tmp_path):
    record = tmp_path / "c1" / "record.json"
    record.parent.mkdir()
    record.write_bytes(b'{"company_id": "c1"}')
    client = _client(Settings(engagement_store="postgres", postgres_dsn=pg, engagements_dir=tmp_path))
    assert client.post("/api/engagement/records", json={"company_id": "c1", "name": "Acme"}).status_code == 200
    res = client.post("/api/engagement/records/c1/issues", params={"name": "Acme"}, json={"theme": "climate_transition"})
    assert res.status_code == 200
    assert record.read_bytes() == b'{"company_id": "c1"}'
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == ["record.json"]


def _run(client: TestClient) -> list:
    out = [client.post("/api/engagement/records", json={"company_id": "c1", "name": "Acme", "sector": "Energy"}).json()]
    opened = client.post("/api/engagement/records/c1/issues", params={"name": "Acme"}, json={"theme": "climate_transition", "severity": "high"}).json()
    issue_id = opened["issue_id"]
    out.append(opened)
    out.append(client.post(f"/api/engagement/records/c1/issues/{issue_id}/escalate", json={"stage": "private_engagement", "reason": "no reply"}).json())
    out.append(client.get("/api/engagement/records").json())
    out.append(client.get("/api/engagement/records/c1").json())
    return [_strip(o) for o in out]


def test_api_parity_file_vs_postgres(pg, tmp_path):
    file_out = _run(_client(Settings(engagements_dir=tmp_path / "f")))
    pg_out = _run(_client(Settings(engagement_store="postgres", postgres_dsn=pg, engagements_dir=tmp_path / "p")))
    assert file_out == pg_out
    assert file_out[2]["issues"][0]["escalation_stage"] == "private_engagement"
