"""The monthly monitoring run: portfolio alerts, then stewardship triggers, for one month.

Blocked (nothing evaluated, nothing written) unless the month's latest holdings load for each portfolio and the
latest ESG load are `ok`. Re-running a month adds no alerts (the evaluators skip what is open) and flags nothing new."""

from __future__ import annotations

import calendar
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from arp.config import Settings
from arp.portfolio.loads import latest_load
from arp.portfolio.monitoring.evaluator import evaluate_news_triggers, evaluate_threshold_rules, list_alerts
from arp.stewardship import monitoring
from arp.stewardship.alerts_feed import LIVE
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


def _blocked_reasons(store: PortfolioStore, month: str, portfolio_ids: list[str], esg_provider: str) -> list[str]:
    reasons = []
    for kind, source in [("holdings", p) for p in portfolio_ids] + [("esg", esg_provider)]:
        load = latest_load(store, kind, source, month)
        if load is None or load.status != "ok":
            reasons.append(f"{kind} load for {source} in {month}: {'missing' if load is None else 'failed'}")
    return reasons


def run_month(
    store: PortfolioStore, settings: Settings, month: str, *, portfolio_ids: list[str], esg_provider: str = "default"
) -> MonthlyRunResult:
    first = datetime.strptime(month, "%Y-%m")  # ValueError if malformed
    reasons = _blocked_reasons(store, month, portfolio_ids, esg_provider)
    if reasons:
        return MonthlyRunResult(status="blocked", blocked_reasons=reasons)
    raised = evaluate_threshold_rules(store, as_of=f"{month}-{calendar.monthrange(first.year, first.month)[1]:02d}")
    raised += evaluate_news_triggers(store, min_severity=settings.portfolio_monitoring_news_min_severity)
    live = [a for a in list_alerts(store) if a.status in LIVE]
    sample = load_sample(settings.frameworks_dir, vote_items(settings.runs_dir), live, from_portfolio(store))
    records = EngagementStore(settings.engagements_dir).list_all()
    triggers = monitoring.evaluate(monitoring.load_graph(), sample, records)
    stored = TriggerStore(settings.stewardship_streams_dir).record_run(month, triggers)
    return MonthlyRunResult(status="ran", alerts=len(raised), triggers=len(stored))
