"""Report finding, task 1: ESEF is fetched first, on by default, through the shared harness."""

import httpx
import pytest

from arp.api.deps import build_registry
from arp.cli._shared import _registry
from arp.config import Settings, get_settings
from arp.ingestion.esef import EsefDocumentSource
from arp.storage.document_store import DocumentContentStore
from tests.postgres_helpers import pg_dsn
from tests.report_finding_fixtures import INDEX_URL, SITE, W, discover

pytestmark = pytest.mark.usefixtures("pg")

CURRENT = "https://filings.xbrl.org/w/2025.zip"


async def test_ac_1(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, esef="current")
    assert CURRENT in run.docs("10-K")


async def test_ac_5(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, esef="old")
    assert "https://filings.xbrl.org/w/2024.zip" in run.docs()


async def test_ac_6(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, esef="current")
    assert run.count(INDEX_URL) == 1


async def test_ac_7(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, esef="error")
    assert run.manifest.failed_count == 0


async def test_ac_8(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, company=W.model_copy(update={"lei": None}), esef="current")
    assert run.host_count("filings.xbrl.org") == 0


async def test_ac_9(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, esef="current", esef_enabled=False)
    assert run.host_count("filings.xbrl.org") == 0


async def test_ac_28(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, esef="none")
    assert run.row["homepage_check"] is None


async def test_ac_44(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, esef="current", routes={SITE + "/": httpx.Response(403)})
    assert CURRENT in run.docs()


async def test_ac_63_and_90(tmp_path, pg, monkeypatch):
    first = await discover(tmp_path, pg, monkeypatch, esef="current")
    second = await discover(tmp_path, pg, monkeypatch, esef="current")
    assert [e["document"]["url"] for e in first.row["new_events"]] == [CURRENT]  # AC-90
    assert second.row["new_events"] == []  # AC-63


async def test_ac_64(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, company=W.model_copy(update={"cik": "123"}), esef="current")
    assert run.edgar.asked == ["w"]


async def test_malformed_period_end_is_not_current(tmp_path, pg, monkeypatch):
    run = await discover(tmp_path, pg, monkeypatch, esef=("2025", "https://filings.xbrl.org/w/x.zip"))
    assert run.manifest.failed_count == 0


def test_ac_65(monkeypatch):
    monkeypatch.delenv("ARP_ESEF_ENABLED", raising=False)
    assert Settings().esef_enabled is True


def test_ac_86(monkeypatch):
    monkeypatch.setenv("ARP_ESEF_ENABLED", "false")
    assert Settings().esef_enabled is False


def test_ac_87(tmp_path):
    store = DocumentContentStore(tmp_path / "store", dsn=pg_dsn())
    assert any(isinstance(s, EsefDocumentSource) for s in build_registry(Settings(), store).sources)


def test_ac_94(tmp_path, monkeypatch):
    monkeypatch.delenv("ARP_ESEF_ENABLED", raising=False)
    for name in ("DOCUMENTS_DIR", "CACHE_DIR", "DOCUMENT_STORE_DIR", "RUNS_DIR", "DISCOVERY_STATE_DIR"):
        monkeypatch.setenv(f"ARP_{name}", str(tmp_path / name.lower()))
    get_settings.cache_clear()
    try:
        assert any(isinstance(s, EsefDocumentSource) for s in _registry().sources)
    finally:
        get_settings.cache_clear()
