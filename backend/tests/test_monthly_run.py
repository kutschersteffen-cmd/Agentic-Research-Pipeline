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


def _spy(store, monkeypatch):
    calls = []
    monkeypatch.setattr(store, "publish_rows", lambda dataset, month, rows: calls.append((dataset, month, rows)), raising=False)
    return calls


def test_publishes_four_datasets_after_a_non_blocked_run(store, settings, monkeypatch):
    calls = _spy(store, monkeypatch)
    _ready(store)
    run_month(store, settings, MONTH, portfolio_ids=_ids(store))
    assert [(d, m) for d, m, _ in calls] == [
        (d, MONTH) for d in ("portfolio_climate_metrics", "alerts", "triggers", "company_profile")
    ]
    assert all(rows for _, _, rows in calls)


def test_publishes_nothing_on_a_blocked_run(store, settings, monkeypatch):
    calls = _spy(store, monkeypatch)
    run_month(store, settings, MONTH, portfolio_ids=_ids(store))
    assert calls == []


def test_esg_uploaded_after_month_end_is_used_by_publishers_and_stewardship(store, settings, monkeypatch):
    from arp.portfolio import monthly_run
    from arp.portfolio.climate.esg_intake import ESG_TEMPLATE_COLUMNS, FIELD_IDS, ingest_esg_bytes

    body = ",".join(ESG_TEMPLATE_COLUMNS) + "\n" + "".join(
        f"{c.company_id}," + ",".join("4242.5" for _ in FIELD_IDS) + "\n" for c in store.list_companies()
    )
    ingest_esg_bytes(store, body.encode(), "e.csv", provider="default", month=MONTH, source_ref=None)  # observed today, after 09-30
    for pid in _ids(store):
        _load(store, "holdings", pid)
    calls = _spy(store, monkeypatch)
    samples = []
    real = monthly_run.from_portfolio
    monkeypatch.setattr(monthly_run, "from_portfolio", lambda *a, **k: samples.append(real(*a, **k)) or samples[-1])
    assert run_month(store, settings, MONTH, portfolio_ids=_ids(store)).status == "ran"
    rows = {d: r for d, _, r in calls}
    assert {r["value"] for r in rows["company_profile"] if r["field_id"] in FIELD_IDS} == {4242.5}
    assert rows["portfolio_climate_metrics"] and all(r["waci"] == pytest.approx(4242.5) for r in rows["portfolio_climate_metrics"])
    issuers = samples[0]["issuers"]
    assert issuers and {i["fields"]["portfolio.climate_carbon_intensity"] for i in issuers} == {4242.5}


def _cli(store, settings, monkeypatch, *args):
    from typer.testing import CliRunner

    from arp.cli import app

    monkeypatch.setattr("arp.cli.portfolio._portfolio_store", lambda: store)
    monkeypatch.setattr("arp.cli.portfolio.get_settings", lambda: settings)
    return CliRunner().invoke(app, ["portfolio", *args])


@pytest.mark.parametrize("bad", ["2026-9", "2026-13", "26-09", "2026-09-01"])
def test_month_must_be_strict_yyyy_mm(store, settings, monkeypatch, bad):
    from fastapi.testclient import TestClient

    from arp.api.deps import get_portfolio_store, settings_dep
    from arp.api.main import app

    _ready(store)
    with pytest.raises(ValueError):
        run_month(store, settings, bad, portfolio_ids=_ids(store))
    assert _cli(store, settings, monkeypatch, "monthly-run", "--month", bad).exit_code == 1
    app.dependency_overrides[get_portfolio_store] = lambda: store
    app.dependency_overrides[settings_dep] = lambda: settings
    try:
        assert TestClient(app).post("/api/portfolio/monthly-run", json={"month": bad}).status_code == 422
    finally:
        app.dependency_overrides.clear()


def _sched_run(store, settings, monkeypatch, pull):
    from arp.portfolio.monitoring import scheduler as sched
    from arp.schemas.portfolio_monitoring import PortfolioMonitoringScheduleConfig

    calls = []
    monkeypatch.setattr(sched, "pull_esg", lambda st, s, month, *a, **k: calls.append(("pull", month)) or pull())
    monkeypatch.setattr(sched, "run_month", lambda st, s, month, **k: calls.append(("run", month)) or run_month(st, s, month, **k))
    config = PortfolioMonitoringScheduleConfig(enabled=True, interval_hours=1, news_min_severity="medium")
    asyncio.run(sched.PortfolioMonitoringScheduler(settings, store)._run(config))
    return calls


def test_scheduler_pulls_esg_for_the_previous_month_before_running_it(store, settings, monkeypatch):
    configured = settings.model_copy(update={"esg_api_base_url": "https://x", "esg_api_token": "t"})
    calls = _sched_run(store, configured, monkeypatch, pull=lambda: None)
    assert [c for c, _ in calls] == ["pull", "run"] and calls[0][1] == calls[1][1]


def test_scheduler_pull_failure_is_logged_and_the_run_still_happens(store, settings, monkeypatch):
    def boom():
        raise ConnectionError("down")

    configured = settings.model_copy(update={"esg_api_base_url": "https://x", "esg_api_token": "t"})
    assert [c for c, _ in _sched_run(store, configured, monkeypatch, pull=boom)] == ["pull", "run"]


def test_scheduler_skips_the_pull_when_the_esg_api_is_not_configured(store, settings, monkeypatch):
    unconfigured = settings.model_copy(update={"esg_api_base_url": None, "esg_api_token": None})
    assert [c for c, _ in _sched_run(store, unconfigured, monkeypatch, pull=lambda: None)] == ["run"]


def test_scheduler_does_not_repull_a_month_that_already_has_an_ok_esg_load(store, settings, monkeypatch):
    from datetime import UTC, datetime, timedelta

    previous = (datetime.now(UTC).date().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    record_load(store, LoadRecord(kind="esg", source_id="default", month=previous, status="ok", content_hash="h"))
    configured = settings.model_copy(update={"esg_api_base_url": "https://x", "esg_api_token": "t"})
    assert "pull" not in [c for c, _ in _sched_run(store, configured, monkeypatch, pull=lambda: None)]  # a failed pull would block it


def test_scheduler_reruns_a_month_only_after_a_newer_load(store, settings, monkeypatch):
    from datetime import UTC, datetime, timedelta

    previous = (datetime.now(UTC).date().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    def load(kind, source):
        record_load(store, LoadRecord(kind=kind, source_id=source, month=previous, status="ok", content_hash="h"))

    for pid in _ids(store):
        load("holdings", pid)
    load("esg", "default")
    unconfigured = settings.model_copy(update={"esg_api_base_url": None, "esg_api_token": None})
    tick = lambda: [c for c, _ in _sched_run(store, unconfigured, monkeypatch, pull=lambda: None)]  # noqa: E731
    assert tick() == ["run"]
    assert tick() == []  # already ran, nothing loaded since
    load("esg", "default")
    assert tick() == ["run"]


def test_status_route_reports_loads_and_the_reasons_run_month_would_block_on(store, settings):
    from fastapi.testclient import TestClient

    from arp.api.deps import get_portfolio_store, settings_dep
    from arp.api.main import app

    first, *rest = _ids(store)
    _load(store, "holdings", first)
    _load(store, "esg", "default", "failed")
    app.dependency_overrides[get_portfolio_store] = lambda: store
    app.dependency_overrides[settings_dep] = lambda: settings
    try:
        c = TestClient(app)
        body = c.get("/api/portfolio/monthly-run/status", params={"month": MONTH}).json()
        assert body["holdings"] == {first: "ok", **{p: "missing" for p in rest}}
        assert body["esg"] == {"provider": "default", "status": "failed"}
        assert body["blocked_reasons"] == run_month(store, settings, MONTH, portfolio_ids=_ids(store)).blocked_reasons
        assert list(c.get("/api/portfolio/monthly-run/status", params={"month": MONTH, "portfolio_ids": first}).json()["holdings"]) == [first]
        assert c.get("/api/portfolio/monthly-run/status", params={"month": "2026-9"}).status_code == 422
    finally:
        app.dependency_overrides.clear()
    assert TriggerStore(settings.stewardship_streams_dir).list_triggers() == []  # read-only: nothing persisted
