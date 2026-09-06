from __future__ import annotations

from arp.portfolio import aggregation, datapoint_mapping
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import SecurityRef
from arp.schemas.portfolio_monitoring import Alert, AlertCategory, AlertRule, AlertStatus, AlertTransition, BreachType
from arp.storage.portfolio_store import PortfolioStore

_COMPARATORS = {
    "gt": lambda value, limit: value > limit,
    "gte": lambda value, limit: value >= limit,
    "lt": lambda value, limit: value < limit,
    "lte": lambda value, limit: value <= limit,
}

_OPEN_STATUSES = (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED, AlertStatus.ESCALATED)
"""RESOLVED and FALSE_POSITIVE are the only two states a breach that's
still active should re-open from -- mirrors
engagement.triggers.run_trigger_screen's open_issues_for_theme dedup,
which only skips a signal when a matching issue is still genuinely open."""


def _breaches(value: float, rule: AlertRule) -> bool:
    return _COMPARATORS[rule.comparator](value, rule.threshold_value)


def _fold_scope_alerts(store: PortfolioStore, scope_id: str) -> dict[str, Alert]:
    """Folds one scope's append-only event log into {alert_id: Alert} with
    each Alert's `status`/`owner` set from the latest `status_changed` row,
    if any -- the same "later rows win" fold
    orchestration.review_queue.latest_decisions already uses elsewhere."""
    alerts: dict[str, Alert] = {}
    for row in store.list_alert_events(scope_id):
        if row["event_type"] == "alert_raised":
            alert = Alert.model_validate(row["alert"])
            alerts[alert.alert_id] = alert
        elif row["event_type"] == "status_changed" and row["alert_id"] in alerts:
            transition = AlertTransition.model_validate(row["transition"])
            update = {"status": transition.status}
            if transition.owner:
                update["owner"] = transition.owner
            alerts[row["alert_id"]] = alerts[row["alert_id"]].model_copy(update=update)
    return alerts


def list_alerts(store: PortfolioStore, *, status: AlertStatus | None = None) -> list[Alert]:
    """Every alert across every scope, current status folded in -- the
    listing every caller (API, CLI, dedup checks below) uses instead of
    reading a scope's raw event log directly."""
    alerts: list[Alert] = []
    for scope_id in store.list_all_alert_scope_ids():
        alerts.extend(_fold_scope_alerts(store, scope_id).values())
    alerts.sort(key=lambda a: a.triggered_at, reverse=True)
    return [a for a in alerts if status is None or a.status == status]


def _has_open_alert(store: PortfolioStore, scope_id: str, rule_id: str) -> bool:
    """Dedup for recurring conditions (threshold rules): a breach that's
    still active never spawns a duplicate, but one that was resolved and
    then recurs opens a fresh alert (mirrors run_trigger_screen)."""
    return any(
        alert.status in _OPEN_STATUSES and alert.rule_id == rule_id
        for alert in _fold_scope_alerts(store, scope_id).values()
    )


def _already_alerted_flag(store: PortfolioStore, scope_id: str, flag_id: str) -> bool:
    """Dedup for a one-time event (a specific NewsRiskFlag): once alerted,
    never re-raised regardless of status -- resolving it should stick,
    unlike a threshold breach which can legitimately recur."""
    return any(alert.source_flag_id == flag_id for alert in _fold_scope_alerts(store, scope_id).values())


def _raise_alert(store: PortfolioStore, alert: Alert) -> Alert:
    store.append_alert_event(alert.scope_id, "alert_raised", {"alert": alert.model_dump(mode="json")})
    return alert


def transition_alert(store: PortfolioStore, scope_id: str, alert_id: str, transition: AlertTransition) -> Alert:
    """Records a human-decided status change -- `transition.decided_by` is
    required (mirrors engagement_store.set_escalation_stage's human
    checkpoint). Raises ValueError if the alert doesn't exist in that scope."""
    alerts = _fold_scope_alerts(store, scope_id)
    if alert_id not in alerts:
        raise ValueError(f"No alert {alert_id!r} in scope {scope_id!r}")
    store.append_alert_event(scope_id, "status_changed", {"alert_id": alert_id, "transition": transition.model_dump(mode="json")})
    return alerts[alert_id].model_copy(update={"status": transition.status, "owner": transition.owner or alerts[alert_id].owner})


def _resolve_holdings_as_of(store: PortfolioStore, as_of: str | None) -> str | None:
    """Unlike api/routers/climate.py's _resolve_as_of, this never raises --
    a scheduled evaluation pass with no holdings ingested yet should skip
    holdings-dependent rule types silently rather than fail the whole run
    (see monitoring/scheduler.py's bare except Exception around this)."""
    if as_of:
        return as_of
    dates = store.all_snapshot_dates()
    return dates[-1] if dates else None


def _classify_aggregate_drift(prior: Alert | None, snapshot_date: str, data_point_values: dict[str, float]) -> BreachType:
    """The one place a real trade/data-restatement distinction is made --
    see BreachType's docstring for why field_threshold/concentration_
    threshold breaches never need this (they're single-caused by
    construction). Compares against the most recent prior alert for the
    same (rule_id, scope_id), regardless of that alert's current status."""
    if prior is None or prior.snapshot_date is None or prior.data_point_values is None:
        return BreachType.UNKNOWN
    snapshot_changed = snapshot_date != prior.snapshot_date
    data_changed = data_point_values != prior.data_point_values
    if snapshot_changed and data_changed:
        return BreachType.MIXED
    if snapshot_changed:
        return BreachType.HOLDINGS_CAUSED
    if data_changed:
        return BreachType.DATA_CAUSED
    return BreachType.UNKNOWN


def _latest_alert_for(store: PortfolioStore, scope_id: str, rule_id: str) -> Alert | None:
    candidates = [a for a in _fold_scope_alerts(store, scope_id).values() if a.rule_id == rule_id]
    return max(candidates, key=lambda a: a.triggered_at, default=None)


def _evaluate_field_threshold(store: PortfolioStore, rule: AlertRule, companies: dict[str, CompanyRef]) -> list[Alert]:
    company_ids = rule.company_ids or list(companies.keys())
    raised: list[Alert] = []
    for company_id in company_ids:
        obs = datapoint_mapping.resolve_field_value(store, company_id, rule.field_id)
        if obs is None or not isinstance(obs.value, (int, float)) or isinstance(obs.value, bool):
            continue
        value = float(obs.value)
        if not _breaches(value, rule):
            continue
        if _has_open_alert(store, company_id, rule.rule_id):
            continue
        raised.append(
            _raise_alert(
                store,
                Alert(
                    rule_id=rule.rule_id,
                    category=AlertCategory.THRESHOLD_BREACH,
                    scope_id=company_id,
                    company_id=company_id,
                    observed_value=value,
                    threshold_value=rule.threshold_value,
                    breach_type=BreachType.DATA_CAUSED,
                    rationale=f"{rule.name}: {rule.field_id} = {value} {rule.comparator} {rule.threshold_value}",
                ),
            )
        )
    return raised


def _evaluate_concentration_threshold(
    store: PortfolioStore,
    rule: AlertRule,
    securities: dict[str, SecurityRef],
    companies: dict[str, CompanyRef],
    as_of: str,
) -> list[Alert]:
    holdings = store.load_holdings_as_of(as_of, rule.portfolio_ids or None)
    if not holdings:
        return []
    result = aggregation.aggregate(
        holdings, securities, companies, group_by="company_id", metric="market_value_sum",
        as_of=as_of, portfolio_filter=rule.portfolio_ids, spec_name=rule.name,
    )
    if not result.total_market_value_eur:
        return []
    raised: list[Alert] = []
    for row in result.rows:
        company_id = row.group_value
        if row.market_value_eur is None or company_id == "(unresolved)":
            continue
        weight = row.market_value_eur / result.total_market_value_eur
        if not _breaches(weight, rule):
            continue
        if _has_open_alert(store, company_id, rule.rule_id):
            continue
        raised.append(
            _raise_alert(
                store,
                Alert(
                    rule_id=rule.rule_id,
                    category=AlertCategory.THRESHOLD_BREACH,
                    scope_id=company_id,
                    company_id=company_id,
                    observed_value=round(weight, 4),
                    threshold_value=rule.threshold_value,
                    breach_type=BreachType.HOLDINGS_CAUSED,
                    snapshot_date=as_of,
                    rationale=f"{rule.name}: {company_id} = {weight:.2%} of NAV {rule.comparator} {rule.threshold_value:.2%}",
                ),
            )
        )
    return raised


def _evaluate_portfolio_aggregate_threshold(
    store: PortfolioStore,
    rule: AlertRule,
    securities: dict[str, SecurityRef],
    companies: dict[str, CompanyRef],
    as_of: str,
) -> list[Alert]:
    holdings = store.load_holdings_as_of(as_of, rule.portfolio_ids or None)
    if not holdings:
        return []
    company_ids = sorted({s.company_id for s in securities.values() if s.company_id})
    values = datapoint_mapping.resolve_field_values_for_universe(store, company_ids, rule.field_id, as_of)
    result = aggregation.aggregate(
        holdings, securities, companies, group_by="portfolio_id", metric="weighted_avg_datapoint",
        as_of=as_of, portfolio_filter=rule.portfolio_ids, data_point_values=values, spec_name=rule.name,
    )
    raised: list[Alert] = []
    for row in result.rows:
        if row.weighted_avg_value is None:
            continue
        if not _breaches(row.weighted_avg_value, rule):
            continue
        portfolio_id = row.group_value
        scope_id = f"portfolio__{portfolio_id}"
        if _has_open_alert(store, scope_id, rule.rule_id):
            continue
        prior = _latest_alert_for(store, scope_id, rule.rule_id)
        breach_type = _classify_aggregate_drift(prior, as_of, values)
        raised.append(
            _raise_alert(
                store,
                Alert(
                    rule_id=rule.rule_id,
                    category=AlertCategory.THRESHOLD_BREACH,
                    scope_id=scope_id,
                    portfolio_id=portfolio_id,
                    observed_value=row.weighted_avg_value,
                    threshold_value=rule.threshold_value,
                    breach_type=breach_type,
                    snapshot_date=as_of,
                    data_point_values=values,
                    rationale=f"{rule.name}: {portfolio_id} = {row.weighted_avg_value} {rule.comparator} {rule.threshold_value}",
                ),
            )
        )
    return raised


def evaluate_threshold_rules(store: PortfolioStore, *, as_of: str | None = None) -> list[Alert]:
    """Evaluates every enabled AlertRule, opening a new Alert for each
    breaching scope that doesn't already have one open for that
    (rule_id, scope_id) -- see _has_open_alert. Never raises: a rule type
    with no data/holdings yet to evaluate against is silently skipped, not
    an error (see monitoring/scheduler.py's bare except around the caller
    for the same reasoning applied one level up)."""
    companies = {c.company_id: c for c in store.list_companies()}
    securities = {s.security_id: s for s in store.list_securities()}
    resolved_as_of = _resolve_holdings_as_of(store, as_of)

    raised: list[Alert] = []
    for rule in store.list_rules(enabled_only=True):
        if rule.rule_type == "field_threshold":
            raised.extend(_evaluate_field_threshold(store, rule, companies))
        elif resolved_as_of is None:
            continue  # concentration_threshold / portfolio_aggregate_threshold need holdings
        elif rule.rule_type == "concentration_threshold":
            raised.extend(_evaluate_concentration_threshold(store, rule, securities, companies, resolved_as_of))
        elif rule.rule_type == "portfolio_aggregate_threshold":
            raised.extend(_evaluate_portfolio_aggregate_threshold(store, rule, securities, companies, resolved_as_of))
    return raised


def evaluate_news_triggers(store: PortfolioStore, *, min_severity: str = "medium") -> list[Alert]:
    """Event-driven triggers (spec item 2): a new NewsRiskFlag at/above
    min_severity becomes a category=news_controversy Alert. Dedup is by
    `source_flag_id`, not (rule_id, scope_id) -- there's no AlertRule
    behind these, they're driven directly off the existing news
    classifier's output (see news/classifier.py)."""
    severity_rank = {"low": 0, "medium": 1, "high": 2}
    floor = severity_rank.get(min_severity, 1)
    raised: list[Alert] = []
    for flag in store.list_flags():
        if severity_rank.get(flag.severity, 0) < floor:
            continue
        if _already_alerted_flag(store, flag.company_id, flag.flag_id):
            continue
        raised.append(
            _raise_alert(
                store,
                Alert(
                    category=AlertCategory.NEWS_CONTROVERSY,
                    scope_id=flag.company_id,
                    company_id=flag.company_id,
                    source_flag_id=flag.flag_id,
                    rationale=flag.rationale,
                ),
            )
        )
    return raised
