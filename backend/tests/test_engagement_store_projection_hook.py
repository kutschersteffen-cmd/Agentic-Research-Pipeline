"""EngagementStore._save's best-effort Postgres hook, without a database: sync_record_if_enabled is
patched out, so these check only when the hook fires (see test_postgres_engagement_projection.py
for the rows it writes)."""

from __future__ import annotations

from arp.storage.engagement_store import EngagementStore


def _calls(monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr(
        "arp.storage.postgres_engagement_projection.sync_record_if_enabled",
        lambda dsn, record: calls.append(record.company_id),
    )
    return calls


def test_no_dsn_means_no_hook(tmp_path, monkeypatch):
    calls = _calls(monkeypatch)
    EngagementStore(tmp_path).get_or_create("acme", "Acme Corp")
    assert calls == []


def test_hook_fires_on_every_mutation(tmp_path, monkeypatch):
    calls = _calls(monkeypatch)
    store = EngagementStore(tmp_path, dsn="dsn")
    store.get_or_create("acme", "Acme Corp")
    store.open_issue("acme", "Acme Corp", theme="board_governance")
    assert calls == ["acme", "acme"]
