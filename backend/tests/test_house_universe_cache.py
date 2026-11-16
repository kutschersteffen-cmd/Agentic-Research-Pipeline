"""Spec stewardship-house-universe-cache: the house universe built once per process and rebuilt when an input changes.

Store S: two held companies (C1, C2) in one portfolio with two holdings snapshot dates, two observation files, source
`portfolio`. The `main` answers (AC-38, AC-39, AC-41) were recorded from `main` d92366c5 (#544 and #548 merged) before
the build changed any code: `ARP_RECORD_MAIN_ANSWERS=1 pytest tests/test_house_universe_cache.py -k record` rewrites them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("zen")

from arp.api.deps import get_portfolio_store, get_stream_store  # noqa: E402
from arp.api.main import app  # noqa: E402
from arp.config import get_settings  # noqa: E402
from arp.portfolio.loads import LoadRecord, record_load  # noqa: E402
from arp.schemas.common import CompanyRef  # noqa: E402
from arp.schemas.portfolio import DataPointObservation, Holding, Portfolio, SecurityRef, SecurityResolution  # noqa: E402
from arp.stewardship.intake import intake_votes  # noqa: E402
from arp.stewardship.process import StreamStore  # noqa: E402
from arp.stewardship.universe import HouseUniverseSetting  # noqa: E402
from arp.storage import portfolio_store  # noqa: E402
from arp.storage.portfolio_store_factory import build_portfolio_store  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "house_universe_cache"
RECORD = os.environ.get("ARP_RECORD_MAIN_ANSWERS") == "1"
DATES = ("2026-09-30", "2026-10-31")
MONTH = "2026-09"  # the earlier month, for the monthly run (AC-41)
ENDPOINTS = (
    "/api/stewardship/worklist?scope=house", "/api/stewardship/worklist/scopes", "/api/stewardship/selection",
    "/api/stewardship/tiers", "/api/stewardship/decision-inputs", "/api/stewardship/studio/coverage/inputs",
    "/api/stewardship/studio/monitoring/triggers", "/api/stewardship/streams/house/flow",
)  # fmt: skip
# keys whose value is the current time or date, left out of every comparison with a recorded answer
NOW_KEYS = {"cycle", "current", "today", "generated_at", "as_of_now", "next_meeting"}


def fill_store_s(store) -> None:
    """Store S's data, written through the (Postgres) portfolio store."""
    store.save_portfolio(Portfolio(portfolio_id="P1", name="Fund P1"))
    for n, cid in enumerate(("C1", "C2"), 1):
        store.save_company(CompanyRef(company_id=cid, name=f"Company {cid}", sector="Energy", country="DE"))
        store.save_security(SecurityRef(security_id=f"{cid}-EQ", name=cid, asset_class="equity", currency="EUR", company_id=cid, isin=f"DE000000000{n}"))
        store.save_resolution(SecurityResolution(security_id=f"{cid}-EQ", company_id=cid, confidence=1.0))
    for k, day in enumerate(DATES):
        store.save_snapshot("P1", day, [
            Holding(holder_id="P1", security_id=f"{cid}-EQ", as_of_date=day, market_value_eur=(n + k) * 1e6, isin=f"DE000000000{n}")
            for n, cid in enumerate(("C1", "C2"), 1)
        ])  # fmt: skip
    for cid, value in (("C1", 120.0), ("C2", 80.0)):  # the two observation files
        store.append_observation(DataPointObservation(company_id=cid, field_id="ghg_intensity", field_name="ghg_intensity", value=value, source="internal_api", observed_at="2026-09-15"))
    for kind, source in (("holdings", "P1"), ("esg", "default")):
        record_load(store, LoadRecord(kind=kind, source_id=source, month=MONTH, status="ok", content_hash="h"))
    # one vote-ledger meeting on C1's ISIN, so the vote ledger maps ISINs to house issuers (the held ISIN map)
    vote = {"external_id": "v1", "isin": "DE0000000001", "issuer_name": "Company C1", "meeting_date": "2026-05-01",
            "item_number": "1", "description": "x", "management_recommendation": "for", "vote": "for"}  # fmt: skip
    assert intake_votes([vote], get_settings().postgres_dsn, "api").rejected == []


@pytest.fixture
def store_s(pg, monkeypatch, tmp_path):
    for name, sub in (("ARP_PORTFOLIOS_DIR", "portfolios"), ("ARP_STEWARDSHIP_STREAMS_DIR", "streams"), ("ARP_ENGAGEMENTS_DIR", "engagements"),
                      ("ARP_FRAMEWORKS_DIR", "frameworks"), ("ARP_RUNS_DIR", "runs")):  # fmt: skip
        monkeypatch.setenv(name, str(tmp_path / sub))
    monkeypatch.setenv("ARP_ENGAGEMENT_STORE", "postgres")
    get_settings.cache_clear()
    get_portfolio_store.cache_clear()
    settings = get_settings()
    store = build_portfolio_store(settings)
    fill_store_s(store)
    HouseUniverseSetting(settings.stewardship_streams_dir).set("portfolio", "tests")
    app.dependency_overrides[get_stream_store] = lambda: StreamStore(settings.stewardship_streams_dir)
    yield store
    app.dependency_overrides.pop(get_stream_store, None)
    get_portfolio_store.cache_clear()
    portfolio_store._LATEST.clear()


@pytest.fixture
def fixture_w(sample_house_universe, pg, monkeypatch, tmp_path):
    monkeypatch.setenv("ARP_ENGAGEMENTS_DIR", str(tmp_path / "engagements"))
    monkeypatch.setenv("ARP_ENGAGEMENT_STORE", "postgres")
    monkeypatch.setenv("ARP_PORTFOLIOS_DIR", str(tmp_path / "portfolios"))
    get_settings.cache_clear()
    root = get_settings().stewardship_streams_dir
    app.dependency_overrides[get_stream_store] = lambda: StreamStore(root)
    yield
    app.dependency_overrides.pop(get_stream_store, None)


def without_now(value):
    """`value` with every NOW_KEYS entry removed, at any depth."""
    if isinstance(value, dict):
        return {k: without_now(v) for k, v in value.items() if k not in NOW_KEYS}
    if isinstance(value, list):
        return [without_now(v) for v in value]
    return value


def answers() -> dict:
    with TestClient(app) as client:
        out = {}
        for url in ENDPOINTS:
            r = client.get(url)
            assert r.status_code == 200, (url, r.text)
            body = r.json()
            if url.startswith("/api/stewardship/worklist?"):
                body.pop("as_of")  # today's date
            out[url] = without_now(body)
    return out


def _record(name: str, value) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / name).write_text(json.dumps(value, indent=1, sort_keys=True, default=str) + "\n")


@pytest.mark.skipif(not RECORD, reason="records the main answers; set ARP_RECORD_MAIN_ANSWERS=1")
def test_record_main_answers_store_s(store_s):
    _record("main_answers_store_s.json", answers())


@pytest.mark.skipif(not RECORD, reason="records the main answers; set ARP_RECORD_MAIN_ANSWERS=1")
def test_record_main_answers_fixture_w(fixture_w):
    _record("main_answers_fixture_w.json", answers())


@pytest.mark.skipif(not RECORD, reason="records the main answers; set ARP_RECORD_MAIN_ANSWERS=1")
def test_record_main_latest_format():
    _record("main_latest_format.json", {"format": portfolio_store._latest_format()})


@pytest.mark.skipif(not RECORD, reason="records the main answers; set ARP_RECORD_MAIN_ANSWERS=1")
def test_record_main_monthly_run(store_s, monkeypatch):
    from arp.portfolio import monthly_run
    from arp.stewardship import process

    seen: dict = {}
    real_load_sample, real_house_isins = monthly_run.load_sample, process.house_isins
    monkeypatch.setattr(monthly_run, "load_sample", lambda *a, **k: seen.setdefault("universe", a[3]) and real_load_sample(*a, **k))
    monkeypatch.setattr(process, "house_isins", lambda: seen.setdefault("held_isins", real_house_isins()))
    result = monthly_run.run_month(store_s, get_settings(), MONTH, portfolio_ids=["P1"])
    assert result.status == "ran", result
    _record("main_monthly_run.json", {"universe": without_now(seen["universe"]), "held_isins": seen.get("held_isins")})
