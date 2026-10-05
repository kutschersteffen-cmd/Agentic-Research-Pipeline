from __future__ import annotations

from datetime import date

import pytest

from arp.config import Settings
from arp.holdings.intake import IntakeError, ingest
from arp.holdings.validate import validate
from arp.portfolio.climate.esg_api_source import pull_esg
from arp.portfolio.climate.esg_intake import FIELD_IDS, ingest_esg_bytes
from arp.portfolio.loads import latest_load
from arp.schemas.common import CompanyRef
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.run_store import RunStore

MONTH = "2026-09"
TOKEN = "s3cret-token-value"
SETTINGS = Settings(esg_api_base_url="https://esg.corp.example/v1", esg_api_token=TOKEN)
CSV = ("company_id," + ",".join(FIELD_IDS) + "\nacme," + ",".join("1.5" for _ in FIELD_IDS) + "\n").encode()


@pytest.fixture
def store(tmp_path):
    s = PortfolioStore(tmp_path / "pf")
    s.save_company(CompanyRef(company_id="acme", name="Acme"))
    return s


def obs(store):
    return [(f, o.value, o.period, o.source) for f in FIELD_IDS for o in store.load_observations("acme", f)]


def test_pull_uses_same_ingest_as_upload(store, tmp_path):
    other = PortfolioStore(tmp_path / "pf2")
    other.save_company(CompanyRef(company_id="acme", name="Acme"))
    pull_esg(store, SETTINGS, MONTH, fetcher=lambda url, headers: CSV)
    ingest_esg_bytes(other, CSV, "esg.csv", provider="default", month=MONTH, source_ref=None)
    assert obs(store) == obs(other) and len(obs(store)) == 6


def test_missing_credentials_records_failed_load(store):
    for s in (Settings(esg_api_base_url=None, esg_api_token=TOKEN), Settings(esg_api_base_url="https://x", esg_api_token=None)):
        with pytest.raises(ValueError):
            pull_esg(store, s, MONTH, fetcher=lambda url, headers: CSV)
        assert latest_load(store, "esg", "default", MONTH).status == "failed"
    assert obs(store) == []


def test_fetcher_error_records_failed_load_and_raises(store):
    def boom(url, headers):
        raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        pull_esg(store, SETTINGS, MONTH, fetcher=boom)
    assert latest_load(store, "esg", "default", MONTH).status == "failed"


def test_token_sent_as_bearer_and_never_logged(store):
    seen = {}

    def boom(url, headers):
        seen.update(url=url, headers=headers)
        raise ConnectionError(f"refused with {headers['Authorization']}")

    with pytest.raises(ConnectionError):
        pull_esg(store, SETTINGS, MONTH, fetcher=boom)
    assert seen["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in latest_load(store, "esg", "default", MONTH).detail
    assert TOKEN not in repr(store.list_governance_events())


def test_pull_twice_same_month_is_unchanged(store):
    assert pull_esg(store, SETTINGS, MONTH, fetcher=lambda u, h: CSV).status == "written"
    assert pull_esg(store, SETTINGS, MONTH, fetcher=lambda u, h: CSV).status == "unchanged"
    assert len(obs(store)) == 6


def test_empty_file_is_rejected_and_records_failed_load(store):
    header_only = ("company_id," + ",".join(FIELD_IDS) + "\n").encode()
    for body in (header_only, b""):
        with pytest.raises(IntakeError):
            pull_esg(store, SETTINGS, MONTH, fetcher=lambda u, h, b=body: b)
        assert latest_load(store, "esg", "default", MONTH).status == "failed"


def _ingest(tmp_path, store):
    v = validate([{"_row": 2, "isin": "US0378331005", "weight": 100, "market_value": 1, "currency": "EUR"}],
                 kind="index", as_of="2026-10-31", today=date(2027, 1, 31))
    return ingest(store, v, kind="index", holder_id="IX1", as_of="2026-10-31", source="file", source_ref="f.csv",
                  principal=None, override_reason=None, run_store=RunStore(tmp_path / "runs"),
                  idmap=IdentifierMapStore(tmp_path / "id.jsonl"))


def test_holdings_ingest_records_load_and_unchanged_reingest_keeps_ok(tmp_path):
    store = PortfolioStore(tmp_path / "pf")
    assert _ingest(tmp_path, store).status == "written"
    first = latest_load(store, "holdings", "IX1", "2026-10")
    assert first.status == "ok" and first.content_hash
    assert _ingest(tmp_path, store).status == "unchanged"
    assert latest_load(store, "holdings", "IX1", "2026-10").status == "ok"


def test_holdings_validation_failure_records_failed_load(tmp_path):
    store = PortfolioStore(tmp_path / "pf")
    v = validate([{"_row": 2, "isin": "bad", "weight": 100}], kind="index", as_of="2026-10-31", today=date(2027, 1, 31))
    with pytest.raises(IntakeError):
        ingest(store, v, kind="index", holder_id="IX1", as_of="2026-10-31", source="file", source_ref=None, principal=None,
               override_reason=None, run_store=RunStore(tmp_path / "runs"), idmap=IdentifierMapStore(tmp_path / "id.jsonl"))
    assert latest_load(store, "holdings", "IX1", "2026-10").status == "failed"


@pytest.mark.parametrize("provider", ["x&token=1", "../default", "a/b", ""])
def test_invalid_provider_rejected_before_the_url_is_built(store, provider):
    called = []
    with pytest.raises(ValueError):
        pull_esg(store, SETTINGS, MONTH, provider=provider, fetcher=lambda u, h: called.append(u) or CSV)
    assert called == []


def _cli(store, settings, monkeypatch, *args):
    from typer.testing import CliRunner

    from arp.cli import app

    monkeypatch.setattr("arp.cli.portfolio._portfolio_store", lambda: store)
    monkeypatch.setattr("arp.cli.portfolio.get_settings", lambda: settings)
    monkeypatch.setattr("arp.portfolio.climate.esg_api_source._http_fetch", lambda url, headers: CSV)
    return CliRunner().invoke(app, ["portfolio", "esg-pull", *args])


def test_cli_esg_pull_exit_codes(store, monkeypatch):
    assert _cli(store, SETTINGS, monkeypatch, "--month", MONTH).exit_code == 0
    assert len(obs(store)) == 6
    assert _cli(store, SETTINGS, monkeypatch, "--month", MONTH, "--provider", "default").exit_code == 0  # unchanged
    assert _cli(store, SETTINGS, monkeypatch, "--month", "2026-9").exit_code == 1
    assert _cli(store, SETTINGS, monkeypatch, "--month", MONTH, "--provider", "x&y").exit_code == 1
    assert _cli(store, Settings(esg_api_base_url=None, esg_api_token=None), monkeypatch, "--month", MONTH).exit_code == 1
