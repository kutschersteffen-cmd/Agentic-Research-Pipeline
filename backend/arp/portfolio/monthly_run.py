"""The monthly monitoring run: portfolio alerts, then stewardship triggers, for one month.

Blocked (nothing evaluated, nothing written) unless the month's latest holdings load for each portfolio and the
latest ESG load are `ok`. Re-running a month adds no alerts (the evaluators skip what is open) and flags nothing new."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from arp.bi import published
from arp.config import Settings
from arp.portfolio.climate.esg_intake import MONTH
from arp.portfolio.loads import latest_load
from arp.portfolio.monitoring.evaluator import evaluate_news_triggers, evaluate_threshold_rules, list_alerts
from arp.stewardship import monitoring
from arp.stewardship.alerts_feed import LIVE
from arp.stewardship.policies import PolicyStore
from arp.stewardship.process import load_sample, vote_items
from arp.stewardship.trigger_store import TriggerStore
from arp.stewardship.universe import from_portfolio
from arp.storage.engagement_store import EngagementStore
from arp.storage.portfolio_store import PortfolioStore


class MonthlyRunResult(BaseModel):
    status: Literal["ran", "blocked"]
    blocked_reasons: list[str] = []
    alerts: int = 0
    triggers: int = 0


def default_esg_provider(store: PortfolioStore, month: str) -> str:
    """The provider used when none is named: `default`, or `simulated` for a month that has only a simulated ESG load
    (`arp showcase load`), so "Run now" works on those months."""
    if latest_load(store, "esg", "default", month) is None and latest_load(store, "esg", "simulated", month) is not None:
        return "simulated"
    return "default"


def load_status(store: PortfolioStore, month: str, portfolio_ids: list[str], esg_provider: str | None = None) -> dict:
    """The month's latest load per source and the reasons a run of it is blocked. Computed on demand, never stored."""
    if not MONTH.fullmatch(month):  # load records are keyed "2026-09"; strptime would also take "2026-9"
        raise ValueError("month must be YYYY-MM")
    esg_provider = esg_provider or default_esg_provider(store, month)

    def status(kind: str, source: str) -> str:
        load = latest_load(store, kind, source, month)
        return "missing" if load is None else load.status

    holdings = {p: status("holdings", p) for p in portfolio_ids}
    esg = status("esg", esg_provider)
    reasons = [f"holdings load for {p} in {month}: {s}" for p, s in holdings.items() if s != "ok"]
    if esg != "ok":
        reasons.append(f"esg load for {esg_provider} in {month}: {esg}")
    return {"month": month, "holdings": holdings, "esg": {"provider": esg_provider, "status": esg}, "blocked_reasons": reasons}


def run_month(
    store: PortfolioStore, settings: Settings, month: str, *, portfolio_ids: list[str], esg_provider: str | None = None
) -> MonthlyRunResult:
    esg_provider = esg_provider or default_esg_provider(store, month)
    reasons = load_status(store, month, portfolio_ids, esg_provider)["blocked_reasons"]
    if reasons:
        return MonthlyRunResult(status="blocked", blocked_reasons=reasons)
    # ESG for month M usually arrives after M ends: date observation lookups to the latest OK ESG load, not the month end
    obs_as_of = max(published.month_end(month), latest_load(store, "esg", esg_provider, month).at[:10])
    raised = evaluate_threshold_rules(store, as_of=published.month_end(month))
    raised += evaluate_news_triggers(store, min_severity=settings.portfolio_monitoring_news_min_severity)
    live = [a for a in list_alerts(store) if a.status in LIVE]
    sample = load_sample(settings.frameworks_dir, vote_items(settings.runs_dir), live, from_portfolio(store, as_of=obs_as_of))
    records = EngagementStore(settings.engagements_dir).list_all()
    triggers = monitoring.evaluate(PolicyStore(settings.stewardship_streams_dir).active("monitoring_rules"), sample, records)
    trigger_store = TriggerStore(settings.stewardship_streams_dir)
    stored = trigger_store.record_run(month, triggers)
    store.publish_rows("portfolio_climate_metrics", month, published.climate_metric_rows(store, month, portfolio_ids, obs_as_of))
    store.publish_rows("alerts", month, published.alert_rows(store))
    store.publish_rows("triggers", month, published.trigger_rows(trigger_store.list_triggers()))
    store.publish_rows("company_profile", month, published.profile_rows(store, month, obs_as_of))
    # what the Home hub's "Monitoring & Alerts" step reads; a blocked run records nothing
    store.append_governance_event("monthly_run_recorded", {"month": month, "alerts": len(raised), "triggers": len(stored)})
    return MonthlyRunResult(status="ran", alerts=len(raised), triggers=len(stored))
