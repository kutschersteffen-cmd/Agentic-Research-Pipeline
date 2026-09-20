"""Unit tests for EngagementStore._save's best-effort Postgres-
projection hook -- no real Postgres instance required:
sync_record_if_enabled (the real work) is monkeypatched out, so these
tests only verify the hook's own contract (does it fire, gated on
ProjectionConfig), not the projection logic itself (see
test_postgres_engagement_projection.py, gated on a real instance, for
that)."""

from __future__ import annotations

from arp.storage.engagement_store import EngagementStore
from arp.storage.postgres_projection_config import ProjectionConfig


def test_no_hook_calls_when_projection_config_is_none(tmp_path):
    store = EngagementStore(tmp_path)
    store.get_or_create("acme", "Acme Corp")  # must not raise


def test_no_hook_calls_when_disabled(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("arp.storage.postgres_engagement_projection.sync_record_if_enabled", lambda *a: calls.append(a))
    config = ProjectionConfig(postgres_dsn="dsn", engagement_projection_enabled=False)
    store = EngagementStore(tmp_path, projection_config=config)

    store.get_or_create("acme", "Acme Corp")

    assert calls == []


def test_hook_fires_on_save(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("arp.storage.postgres_engagement_projection.sync_record_if_enabled", lambda config, record: calls.append(record.company_id))
    config = ProjectionConfig(postgres_dsn="dsn", engagement_projection_enabled=True)
    store = EngagementStore(tmp_path, projection_config=config)

    store.get_or_create("acme", "Acme Corp")

    assert calls == ["acme"]


def test_hook_fires_on_every_mutation(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("arp.storage.postgres_engagement_projection.sync_record_if_enabled", lambda config, record: calls.append(record.company_id))
    config = ProjectionConfig(postgres_dsn="dsn", engagement_projection_enabled=True)
    store = EngagementStore(tmp_path, projection_config=config)

    store.get_or_create("acme", "Acme Corp")
    store.open_issue("acme", "Acme Corp", theme="board_governance")

    assert calls == ["acme", "acme"]


def test_no_dsn_means_hook_does_not_fire_even_if_flag_enabled(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("arp.storage.postgres_engagement_projection.sync_record_if_enabled", lambda *a: calls.append(a))
    config = ProjectionConfig(postgres_dsn=None, engagement_projection_enabled=True)
    store = EngagementStore(tmp_path, projection_config=config)

    store.get_or_create("acme", "Acme Corp")

    assert calls == []
