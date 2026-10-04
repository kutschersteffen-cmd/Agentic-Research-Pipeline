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
from arp.extraction.pipeline import UnreleasedFieldError, create_extraction_run
from arp.schemas.common import CompanyRef
from arp.schemas.datapoints import DataPointSchema, FieldDataType, FieldDefinition, FieldStatus
from arp.storage.run_store import RunStore
from arp.storage.schema_registry import FieldVersionError, SchemaRegistry

ACME = CompanyRef(company_id="c1", name="Acme")


def _schema(**kw) -> DataPointSchema:
    f = FieldDefinition(
        name="capex", description="Capex.", data_type=FieldDataType.NUMBER, extraction_instructions="Find it.", seed_keywords=["capex"]
    )
    return DataPointSchema(name="S", fields=[f], **kw)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        anthropic_api_key="x", runs_dir=tmp_path / "runs", schema_registry_dir=tmp_path / "schemas",
        documents_dir=tmp_path / "docs", cache_dir=tmp_path / "cache", discovery_state_dir=tmp_path / "disc",
    )


def _released(settings) -> DataPointSchema:
    reg = SchemaRegistry(settings.schema_registry_dir)
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


def test_released_run_allowed(settings):
    store = RunStore(settings.runs_dir)
    schema = _released(settings)
    run_id = create_extraction_run(schema, [ACME], settings, store)
    params = store.load_manifest(run_id).params
    assert params["trial"] is False and params["schema_version"] == f"{schema.schema_id}:v1"


def test_released_field_change_requires_new_version(tmp_path):
    reg = SchemaRegistry(tmp_path)
    s = reg.release(*(lambda x: (x.schema_id, x.version))(reg.save(_schema())))
    edited = s.model_copy(deep=True)
    edited.fields[0].description = "Changed."
    with pytest.raises(FieldVersionError):
        reg.save(edited)
    edited.fields[0].version = 2
    assert reg.save(edited).version == 2
    assert reg.get(s.schema_id, 1).fields[0].description == "Capex."
    assert reg.get(s.schema_id).release_flag is False


def test_save_discards_client_release_metadata(tmp_path):
    reg = SchemaRegistry(tmp_path)
    s = reg.save(_schema(release_flag=True, released_by="mallory", released_at="2020-01-01"))
    assert (s.release_flag, s.released_by, s.released_at) == (False, None, None)
    stored = reg.get(s.schema_id)
    assert (stored.release_flag, stored.released_by, stored.released_at) == (False, None, None)
    edited = stored.model_copy(update={"name": "S2", "released_by": "mallory"})
    v2 = reg.save(edited)
    assert v2.version == 2 and v2.released_by is None


def test_resave_unchanged_returns_same_version(tmp_path):
    reg = SchemaRegistry(tmp_path)
    s = reg.save(_schema())
    assert reg.save(s).version == 1 and len(reg.list_index()) == 1


def test_snapshot_and_index_written(settings):
    store = RunStore(settings.runs_dir)
    run_id = create_extraction_run(_schema(), [ACME], settings, store, trial=True)
    from arp.extraction.pipeline import load_run_schema

    snap = load_run_schema(store, run_id)
    (row,) = SchemaRegistry(settings.schema_registry_dir).list_index()
    assert row["schema_id"] == snap.schema_id and row["version"] == 1
    assert (settings.schema_registry_dir / snap.schema_id / "v1.json").exists()
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


def test_release_route_requires_approver(settings, monkeypatch):
    store = RunStore(settings.runs_dir)
    reg = SchemaRegistry(settings.schema_registry_dir)
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


def test_new_field_quality_not_audited(tmp_path):
    q = SchemaRegistry(tmp_path).quality("f1", 1)
    assert (q.field_id, q.version, q.first_audit_passed, q.audited_by, q.audited_at) == ("f1", 1, False, None, None)


def test_record_first_audit_persists(tmp_path):
    reg = SchemaRegistry(tmp_path)
    fid = _fid(reg)
    reg.record_first_audit(fid, 1, "u1")
    q = SchemaRegistry(tmp_path).quality(fid, 1)
    assert q.first_audit_passed is True and q.audited_by == "u1" and q.audited_at


def test_new_version_starts_unaudited(tmp_path):
    reg = SchemaRegistry(tmp_path)
    fid = _fid(reg)
    reg.record_first_audit(fid, 1, "u1")
    assert reg.quality(fid, 2).first_audit_passed is False


def test_first_audit_unknown_field_version_refused(tmp_path):
    reg = SchemaRegistry(tmp_path)
    fid = _fid(reg)
    for args in ((fid, 2), ("nope", 1)):
        with pytest.raises(KeyError):
            reg.record_first_audit(*args, "u1")
        assert reg.quality(*args).first_audit_passed is False


def test_first_audit_route_requires_approver(settings, monkeypatch):
    store = RunStore(settings.runs_dir)
    reg = SchemaRegistry(settings.schema_registry_dir)
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
