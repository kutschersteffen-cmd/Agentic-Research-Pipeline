"""`arp bi bootstrap` failure path, offline: a fake client stands in for Superset."""

from __future__ import annotations

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
