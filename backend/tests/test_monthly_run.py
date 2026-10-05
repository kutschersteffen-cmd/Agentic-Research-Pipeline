from __future__ import annotations

import asyncio

import pytest

from arp.config import Settings
from arp.portfolio.loads import LoadRecord, record_load
from arp.portfolio.mock_data import generate_demo_dataset
from arp.portfolio.monitoring.evaluator import list_alerts
from arp.portfolio.monthly_run import run_month
from arp.schemas.portfolio_monitoring import AlertRule
from arp.stewardship.trigger_store import TriggerStore, trigger_id
from arp.storage.portfolio_store import PortfolioStore

MONTH = "2026-09"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        engagements_dir=tmp_path / "eng",
        stewardship_streams_dir=tmp_path / "streams",
        frameworks_dir=tmp_path / "fw",
        runs_dir=tmp_path / "runs",
    )


@pytest.fixture
def store(tmp_path):
    s = PortfolioStore(tmp_path / "pf")
    asyncio.run(generate_demo_dataset(s))
    s.save_rule(AlertRule(name="ci", rule_type="field_threshold", field_id="climate_carbon_intensity", comparator="gte", threshold_value=0))
    return s


def _load(store, kind, source_id, status="ok"):
    record_load(store, LoadRecord(kind=kind, source_id=source_id, month=MONTH, status=status, content_hash="h"))


def _ids(store):
    return [p.portfolio_id for p in store.list_portfolios()]


def _ready(store, esg_status="ok"):
    for pid in _ids(store):
        _load(store, "holdings", pid)
    _load(store, "esg", "default", esg_status)


def test_blocked_when_holdings_load_missing(store, settings):
    _load(store, "esg", "default")
    r = run_month(store, settings, MONTH, portfolio_ids=_ids(store))
    assert r.status == "blocked" and len(r.blocked_reasons) == len(_ids(store))
    assert list_alerts(store) == []


def test_blocked_when_esg_load_failed_evaluates_nothing(store, settings):
    _ready(store, esg_status="failed")
    r = run_month(store, settings, MONTH, portfolio_ids=_ids(store))
    assert r.status == "blocked" and any("esg" in x for x in r.blocked_reasons)
    assert list_alerts(store) == [] and TriggerStore(settings.stewardship_streams_dir).list_triggers() == []


def test_later_failed_load_beats_earlier_ok(store, settings):
    _ready(store)
    _load(store, "holdings", _ids(store)[0], "failed")
    assert run_month(store, settings, MONTH, portfolio_ids=_ids(store)).status == "blocked"


def test_runs_all_steps_in_order_on_seeded_demo(store, settings):
    _ready(store)
    r = run_month(store, settings, MONTH, portfolio_ids=_ids(store))
    assert r.status == "ran" and r.blocked_reasons == []
    assert r.alerts == len(list_alerts(store)) > 0
    stored = TriggerStore(settings.stewardship_streams_dir).list_triggers()
    assert r.triggers == len(stored) > 0 and all(t.is_new for t in stored)


def test_rerun_same_month_creates_no_duplicate_alerts_or_new_flags(store, settings):
    _ready(store)
    run_month(store, settings, MONTH, portfolio_ids=_ids(store))
    n_alerts = len(list_alerts(store))
    again = run_month(store, settings, MONTH, portfolio_ids=_ids(store))
    assert len(list_alerts(store)) == n_alerts and again.alerts == 0
    assert all(t.is_new for t in TriggerStore(settings.stewardship_streams_dir).list_triggers())  # unchanged: still the first run's flags


def test_empty_universe_runs_with_zero_triggers(tmp_path, settings):
    s = PortfolioStore(tmp_path / "empty")
    _load(s, "esg", "default")
    r = run_month(s, settings, MONTH, portfolio_ids=[])
    assert (r.status, r.alerts, r.triggers) == ("ran", 0, 0)


def test_route_defaults_to_all_portfolios_and_blocks_without_loads(store, settings):
    from fastapi.testclient import TestClient

    from arp.api.deps import get_portfolio_store, settings_dep
    from arp.api.main import app

    app.dependency_overrides[get_portfolio_store] = lambda: store
    app.dependency_overrides[settings_dep] = lambda: settings
    try:
        c = TestClient(app)
        assert c.post("/api/portfolio/monthly-run", json={"month": MONTH}).json()["status"] == "blocked"
        _ready(store)
        assert c.post("/api/portfolio/monthly-run", json={"month": MONTH}).json()["status"] == "ran"
        assert c.post("/api/portfolio/monthly-run", json={"month": "nope"}).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_scheduler_run_swallows_monthly_run_failure(store, settings, monkeypatch):
    from arp.portfolio.monitoring import scheduler as sched
    from arp.schemas.portfolio_monitoring import PortfolioMonitoringScheduleConfig

    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(sched, "run_month", boom)
    config = PortfolioMonitoringScheduleConfig(enabled=True, interval_hours=1, news_min_severity="medium")
    asyncio.run(sched.PortfolioMonitoringScheduler(settings, store)._run(config))


def test_run_follows_the_activated_monitoring_rules(store, settings):
    import copy

    from arp.stewardship import monitoring
    from arp.stewardship.policies import PolicyStore
    from arp.stewardship.universe import from_portfolio

    _ready(store)
    graph = copy.deepcopy(monitoring.load_graph())
    table = next(n for n in graph["nodes"] if n["id"] == "monitoring_rules")
    table["content"]["rules"][0]["clti"] = ""  # the first rule now fires for every issuer
    policies = PolicyStore(settings.stewardship_streams_dir)
    version = policies.save("monitoring_rules", graph, "", "designer", from_portfolio(store))
    policies.activate("monitoring_rules", version, "approver")
    rule = table["content"]["rules"][0]["_id"]
    run_month(store, settings, MONTH, portfolio_ids=_ids(store))
    issuers = [i["issuer_id"] for i in from_portfolio(store)["issuers"]]
    stored = {t.trigger_id for t in TriggerStore(settings.stewardship_streams_dir).list_triggers()}
    assert issuers and {trigger_id(i, rule) for i in issuers} <= stored
