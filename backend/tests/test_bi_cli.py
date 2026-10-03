"""`arp bi bootstrap` failure path, offline: a fake client stands in for Superset."""

from __future__ import annotations

import json
from contextlib import nullcontext
from types import SimpleNamespace

from typer.testing import CliRunner

from arp.bi.superset_client import SupersetError
from arp.cli import app
from arp.config import get_settings


def test_bootstrap_prints_superset_response_body_for_the_operator(monkeypatch):
    for name, value in {
        "ARP_POSTGRES_DSN": "postgresql+psycopg://u:p@localhost:5432/arp",
        "ARP_SUPERSET_PASSWORD": "x" * 20,
        "ARP_BI_READER_PASSWORD": "y" * 20,
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()

    class FakeClient:
        def __init__(self, *args):
            pass

        def ensure_database(self, *args):
            raise SupersetError(422, '{"message": "bad uri"}')

    monkeypatch.setattr("arp.bi.superset_client.SupersetClient", FakeClient)
    monkeypatch.setattr("arp.bi.views.create_bi_views", lambda conn: None)
    monkeypatch.setattr("arp.bi.views.ensure_reader_role", lambda conn, pw: None)
    monkeypatch.setattr("arp.storage.postgres.get_engine", lambda dsn: SimpleNamespace(begin=lambda: nullcontext()))
    try:
        result = CliRunner().invoke(app, ["bi", "bootstrap"])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 1
    assert "HTTP 422" in result.stderr and '"bad uri"' in result.stderr
    assert '"bad uri"' not in result.stdout


def test_bootstrap_rejects_placeholder_reader_password(monkeypatch):
    monkeypatch.setenv("ARP_POSTGRES_DSN", "postgresql+psycopg://u:p@localhost:5432/arp")
    monkeypatch.setenv("ARP_SUPERSET_PASSWORD", "x" * 20)
    monkeypatch.setenv("ARP_BI_READER_PASSWORD", "change-me-dev-only")
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["bi", "bootstrap"])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 1 and "placeholder" in result.stderr and "openssl rand" in result.stderr


def _bootstrap_offline(monkeypatch, provision) -> tuple:
    """Runs `arp bi bootstrap` against a fake Superset; returns (result, synced descriptions)."""
    for name, value in {
        "ARP_POSTGRES_DSN": "postgresql+psycopg://u:p@localhost:5432/arp",
        "ARP_SUPERSET_PASSWORD": "x" * 20,
        "ARP_BI_READER_PASSWORD": "y" * 20,
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    synced = []

    class FakeClient:
        def __init__(self, *args):
            pass

        def ensure_database(self, *args):
            return 1

        def ensure_dataset(self, db, schema, table):
            return hash(table) % 1000

        def refresh_dataset(self, id):
            pass

        def sync_metrics(self, id, metrics):
            pass

        def sync_descriptions(self, id, description, columns):
            synced.append((id, description, columns))

    monkeypatch.setattr("arp.bi.superset_client.SupersetClient", FakeClient)
    monkeypatch.setattr("arp.bi.views.create_bi_views", lambda conn: None)
    monkeypatch.setattr("arp.bi.views.ensure_reader_role", lambda conn, pw: None)
    monkeypatch.setattr("arp.storage.postgres.get_engine", lambda dsn: SimpleNamespace(begin=lambda: nullcontext()))
    monkeypatch.setattr("arp.bi.templates.provision", provision)
    try:
        return CliRunner().invoke(app, ["bi", "bootstrap"]), synced
    finally:
        get_settings.cache_clear()


def test_bootstrap_syncs_descriptions_for_every_dataset(monkeypatch):
    from arp.bi.catalog import VIEW_DATASETS

    result, synced = _bootstrap_offline(monkeypatch, lambda client, t: "unchanged")
    assert result.exit_code == 0, result.output
    assert sorted(s[1] for s in synced) == sorted(d.description for d in VIEW_DATASETS.values())
    assert sorted(len(s[2]) for s in synced) == sorted(len(d.columns) for d in VIEW_DATASETS.values())


def test_bootstrap_provisions_templates(monkeypatch):
    seen = []

    def provision(client, template):
        seen.append(template.slug)
        return "created"

    result, _ = _bootstrap_offline(monkeypatch, provision)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["templates"] == {"arp-risk-exposure": "created"}
    assert seen == ["arp-risk-exposure"]


def test_bootstrap_template_error_exits_nonzero(monkeypatch):
    from arp.bi.service import BIError

    def provision(client, template):
        raise BIError(f"Template {template.slug}: Chart 'X': unknown groupby column 'fund'")

    result, _ = _bootstrap_offline(monkeypatch, provision)
    assert result.exit_code == 1
    assert "unknown groupby column 'fund'" in result.stderr and result.stdout == ""
