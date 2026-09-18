"""Unit tests for RunStore.save_manifest's best-effort Postgres-projection
hook -- no real Postgres instance required: sync_run_if_enabled/
materialize_run_if_enabled (the real work) are monkeypatched out, so
these tests only verify the hook's own contract (which statuses trigger
it, gating on ProjectionConfig), not the projection logic itself (see
test_postgres_company_records_projection.py/
test_postgres_company_facts_projection.py for that)."""

from __future__ import annotations

from arp.schemas.common import JobStatus, RunManifest
from arp.storage.postgres_projection_config import ProjectionConfig
from arp.storage.run_store import RunStore


def _manifest(status: JobStatus, run_id: str = "run_1") -> RunManifest:
    return RunManifest(run_id=run_id, run_type="extraction", status=status)


def test_no_hook_calls_when_projection_config_is_none(tmp_path):
    store = RunStore(tmp_path)
    store.save_manifest(_manifest(JobStatus.COMPLETED))  # must not raise


def test_no_hook_calls_when_disabled(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("arp.storage.postgres_company_records_projection.sync_run_if_enabled", lambda *a: calls.append(a))
    config = ProjectionConfig(postgres_dsn="dsn", company_records_projection_enabled=False)
    store = RunStore(tmp_path, projection_config=config)

    store.save_manifest(_manifest(JobStatus.COMPLETED))

    assert calls == []


def test_hook_fires_on_completed(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("arp.storage.postgres_company_records_projection.sync_run_if_enabled", lambda config, rs, run_id: calls.append(run_id))
    config = ProjectionConfig(postgres_dsn="dsn", company_records_projection_enabled=True)
    store = RunStore(tmp_path, projection_config=config)

    store.save_manifest(_manifest(JobStatus.COMPLETED, run_id="run_42"))

    assert calls == ["run_42"]


def test_hook_does_not_fire_on_pending_or_running(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("arp.storage.postgres_company_records_projection.sync_run_if_enabled", lambda *a: calls.append(a))
    config = ProjectionConfig(postgres_dsn="dsn", company_records_projection_enabled=True)
    store = RunStore(tmp_path, projection_config=config)

    store.save_manifest(_manifest(JobStatus.PENDING))
    store.save_manifest(_manifest(JobStatus.RUNNING))

    assert calls == []


def test_hook_fires_for_both_projections_when_both_enabled(tmp_path, monkeypatch):
    records_calls = []
    facts_calls = []
    monkeypatch.setattr(
        "arp.storage.postgres_company_records_projection.sync_run_if_enabled", lambda config, rs, run_id: records_calls.append(run_id)
    )
    monkeypatch.setattr(
        "arp.storage.postgres_company_facts_projection.materialize_run_if_enabled", lambda config, rs, run_id: facts_calls.append(run_id)
    )
    config = ProjectionConfig(postgres_dsn="dsn", company_records_projection_enabled=True, company_facts_projection_enabled=True)
    store = RunStore(tmp_path, projection_config=config)

    store.save_manifest(_manifest(JobStatus.PARTIALLY_COMPLETED, run_id="run_7"))

    assert records_calls == ["run_7"]
    assert facts_calls == ["run_7"]
