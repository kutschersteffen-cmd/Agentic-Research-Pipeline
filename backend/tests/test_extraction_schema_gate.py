from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from arp.api import run_scheduling
from arp.api.auth import Principal, current_user
from arp.api.deps import get_registry, get_run_store, settings_dep
from arp.api.routers import extraction as extraction_router
from arp.config import Settings
from arp.db.fields import SchemaRegistry
from arp.extraction.pipeline import UnreleasedFieldError, create_extraction_run
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition, FieldStatus
from arp.storage.run_store import RunStore

ACME = CompanyRef(company_id="c1", name="Acme")


def _schema(**kw) -> DataPointSchema:
    f = FieldDefinition(
        name="capex", description="Capex.", data_type=FieldDataType.NUMBER, extraction_instructions="Find it.", seed_keywords=["capex"]
    )
    return DataPointSchema(name="S", fields=[f], **kw)


@pytest.fixture
def settings(tmp_path, pg):
    return Settings(
        anthropic_api_key="x", runs_dir=tmp_path / "runs",
        documents_dir=tmp_path / "docs", cache_dir=tmp_path / "cache", discovery_state_dir=tmp_path / "disc",
    )


def _released(pg) -> DataPointSchema:
    reg = SchemaRegistry(pg)
    s = reg.save(_schema())
    return reg.release(s.schema_id, s.version)


def test_run_with_draft_field_is_refused(settings):
    schema = _schema()
    store = RunStore(settings.runs_dir)
    with pytest.raises(UnreleasedFieldError, match=schema.fields[0].field_id):
        create_extraction_run(schema, [ACME], settings, store)
    assert not settings.runs_dir.exists() or not any(settings.runs_dir.iterdir())


def test_trial_run_allows_draft_and_records_trial(settings):
    store = RunStore(settings.runs_dir)
    run_id = create_extraction_run(_schema(), [ACME], settings, store, trial=True)
    assert store.load_manifest(run_id).params["trial"] is True


def test_released_run_allowed(pg, settings):
    store = RunStore(settings.runs_dir)
    schema = _released(pg)
    run_id = create_extraction_run(schema, [ACME], settings, store)
    params = store.load_manifest(run_id).params
    assert params["trial"] is False and params["schema_version"] == f"{schema.schema_id}:v1"


def test_snapshot_and_index_written(pg, settings):
    store = RunStore(settings.runs_dir)
    run_id = create_extraction_run(_schema(), [ACME], settings, store, trial=True)
    from arp.extraction.pipeline import load_run_schema

    snap = load_run_schema(store, run_id)
    (row,) = SchemaRegistry(pg).list_index()
    assert row["schema_id"] == snap.schema_id and row["version"] == 1
    assert load_run_schema(store, "missing") is None


def test_old_schema_json_loads():
    old = {"field_id": "f", "name": "n", "description": "d", "data_type": "number", "extraction_instructions": "i"}
    f = FieldDefinition.model_validate(old)
    assert f.status == FieldStatus.DRAFT == "draft" and f.version == 1
    s = DataPointSchema.model_validate({"schema_id": "s", "name": "n", "fields": [old]})
    assert s.version == 1 and s.release_flag is False


def _client(settings, store, role, monkeypatch):
    class _L:  # stands in for an LLM client; the background run is never awaited
        pass

    monkeypatch.setattr(run_scheduling, "build_llm_client", lambda s: _L())
    monkeypatch.setattr(run_scheduling, "build_verifier_llm_client", lambda s: _L())
    app = FastAPI()
    app.include_router(extraction_router.router)

    @app.exception_handler(ValueError)
    async def _ve(request, exc):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[get_run_store] = lambda: store
    app.dependency_overrides[get_registry] = lambda: None
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u", name="U", role=role)
    return TestClient(app)


def test_start_unreleased_custom_run_is_400(settings, monkeypatch):
    store = RunStore(settings.runs_dir)
    schema = _schema()
    r = _client(settings, store, "approver", monkeypatch).post(
        "/api/extraction/start",
        json={"profile": "custom", "datapoint_schema": schema.model_dump(mode="json"), "companies": [ACME.model_dump(mode="json")]},
    )
    assert r.status_code == 400 and schema.fields[0].field_id in r.json()["detail"]


def test_release_route_requires_approver(pg, settings, monkeypatch):
    store = RunStore(settings.runs_dir)
    reg = SchemaRegistry(pg)
    s = reg.save(_schema())
    url = f"/api/extraction/schemas/{s.schema_id}/versions/1/release"
    assert _client(settings, store, "analyst", monkeypatch).post(url).status_code == 403
    ok = _client(settings, store, "approver", monkeypatch).post(url, json={"released_by": "mallory"})
    assert ok.status_code == 200 and ok.json()["release_flag"] is True
    assert ok.json()["released_by"] == "u" and ok.json()["released_at"]
    assert ok.json()["fields"][0]["status"] == "released"


def test_register_schema_requires_analyst(settings, monkeypatch):
    body = _schema().model_dump(mode="json")
    assert _client(settings, RunStore(settings.runs_dir), "viewer", monkeypatch).post("/api/extraction/schemas", json=body).status_code == 403


def test_schema_routes_register_list_get(settings, monkeypatch):
    c = _client(settings, RunStore(settings.runs_dir), "viewer", monkeypatch)
    c.app.dependency_overrides[current_user] = lambda: Principal(user_id="u", name="U", role="analyst")
    s = c.post("/api/extraction/schemas", json=_schema().model_dump(mode="json")).json()
    assert c.get("/api/extraction/schemas").json()[0]["schema_id"] == s["schema_id"]
    assert c.get(f"/api/extraction/schemas/{s['schema_id']}", params={"version": 1}).json()["version"] == 1


def _fid(reg) -> str:
    return reg.save(_schema()).fields[0].field_id


def test_first_audit_route_requires_approver(pg, settings, monkeypatch):
    store = RunStore(settings.runs_dir)
    reg = SchemaRegistry(pg)
    fid = _fid(reg)
    url = f"/api/extraction/fields/{fid}/versions/1/first-audit"
    assert _client(settings, store, "analyst", monkeypatch).post(url).status_code == 403
    assert reg.quality(fid, 1).first_audit_passed is False
    ok = _client(settings, store, "approver", monkeypatch).post(url)
    assert ok.status_code == 200 and ok.json()["audited_by"] == "u"
    assert reg.quality(fid, 1).first_audit_passed is True
    missing = f"/api/extraction/fields/{fid}/versions/2/first-audit"
    assert _client(settings, store, "approver", monkeypatch).post(missing).status_code == 404
    assert reg.quality(fid, 2).first_audit_passed is False
