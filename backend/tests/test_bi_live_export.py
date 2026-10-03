"""Spike: does a hand-built dashboard round-trip through Superset's export/import API?

Skipped unless ARP_TEST_SUPERSET_URL is set (same stack and prerequisites as
test_bi_live_superset.py, plus ARP_BI_READER_PASSWORD for the masked database password).
The second scenario also needs ARP_TEST_SUPERSET_URL2: a second Superset on a fresh,
empty metadata DB (it is bootstrapped here, then its copy of the dashboard is dropped).

WARNING: this deletes `arp-risk-exposure` (and its charts) on the targets, during and after
every test. It only runs with ARP_TEST_SUPERSET_DESTRUCTIVE=1, a promise that the URLs point
at throwaway Superset instances."""

from __future__ import annotations

import contextlib
import json
import os

import httpx
import pytest
from typer.testing import CliRunner

from arp.bi.superset_client import SupersetClient, SupersetError
from arp.cli import app
from arp.config import get_settings

URL = os.environ.get("ARP_TEST_SUPERSET_URL")
URL2 = os.environ.get("ARP_TEST_SUPERSET_URL2")
SLUG = "arp-risk-exposure"
pytestmark = [
    pytest.mark.live_superset,
    pytest.mark.skipif(not URL, reason="ARP_TEST_SUPERSET_URL not set -- live Superset"),
    pytest.mark.skipif(
        os.environ.get("ARP_TEST_SUPERSET_DESTRUCTIVE") != "1",
        reason="ARP_TEST_SUPERSET_DESTRUCTIVE=1 not set -- this test deletes dashboards",
    ),
]


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("ARP_SUPERSET_URL", URL)
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def drop_dashboard_after(settings):
    """Nothing the tests create or import may outlive them, on either Superset."""
    yield
    for url in (URL, URL2):
        if not url:
            continue
        with contextlib.suppress(SupersetError, httpx.HTTPError):  # one failure must not leak the rest
            client = SupersetClient(url, settings.superset_user, settings.superset_password)
            dash_id = client.find_dashboard(SLUG)
            if dash_id is not None:
                charts = client.dashboard_charts(dash_id)
                client.delete_dashboard(dash_id)
                for cid in charts:
                    client.delete_chart(cid)


def _bootstrap(monkeypatch, url: str) -> None:
    monkeypatch.setenv("ARP_SUPERSET_URL", url)
    get_settings.cache_clear()
    result = CliRunner().invoke(app, ["bi", "bootstrap"])
    assert result.exit_code == 0, result.output
    json.loads(result.output)


def _drop_dashboard_only(client: SupersetClient) -> None:
    dash_id = client.find_dashboard(SLUG)
    if dash_id is not None:
        client.delete_dashboard(dash_id)  # charts and datasets stay


def _assert_restored(client: SupersetClient) -> None:
    dash_id = client.find_dashboard(SLUG)
    assert dash_id is not None
    assert len(client.dashboard_charts(dash_id)) == 8
    assert client.get_dashboard(dash_id)["published"] is False


def _passwords() -> dict[str, str]:
    return {"databases/arp_bi.yaml": os.environ["ARP_BI_READER_PASSWORD"]}


def test_export_then_import_roundtrip(settings, monkeypatch):
    _bootstrap(monkeypatch, URL)
    client = SupersetClient(URL, settings.superset_user, settings.superset_password)
    bundle = client.export_dashboard(client.find_dashboard(SLUG))
    _drop_dashboard_only(client)
    try:
        assert client.find_dashboard(SLUG) is None
        client.import_dashboard(bundle, _passwords())
        _assert_restored(client)
        client.import_dashboard(bundle, _passwords())  # overwrite=true makes a repeat harmless
        _assert_restored(client)
    finally:
        if client.find_dashboard(SLUG) is None:  # a failed import must not leave the target without it
            _bootstrap(monkeypatch, URL)


@pytest.mark.skipif(not URL2, reason="ARP_TEST_SUPERSET_URL2 not set -- second Superset on a fresh metadata DB")
def test_import_onto_fresh_metadata_db(settings, monkeypatch):
    _bootstrap(monkeypatch, URL)
    src = SupersetClient(URL, settings.superset_user, settings.superset_password)
    bundle = src.export_dashboard(src.find_dashboard(SLUG))
    _bootstrap(monkeypatch, URL2)  # datasets exist on the target before the import
    dst = SupersetClient(URL2, settings.superset_user, settings.superset_password)
    datasets_before = {n: dst.find_dataset(dst.find_database("arp_bi"), "bi", n) for n in ("holdings", "holdings_history")}
    dash_id = dst.find_dashboard(SLUG)
    for cid in dst.dashboard_charts(dash_id):
        dst.delete_chart(cid)
    dst.delete_dashboard(dash_id)
    dst.import_dashboard(bundle, _passwords())
    _assert_restored(dst)
    # Datasets matched by UUID: no duplicates, same ids as before the import.
    assert {n: dst.find_dataset(dst.find_database("arp_bi"), "bi", n) for n in datasets_before} == datasets_before
