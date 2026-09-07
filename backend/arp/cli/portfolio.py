from __future__ import annotations

import asyncio
import json

import typer

from arp.cli._shared import _portfolio_directories, _portfolio_store
from arp.config import get_settings
from arp.llm.factory import build_llm_client
from arp.portfolio import analytics, governance, qa_agent
from arp.portfolio.mock_data import generate_demo_dataset
from arp.portfolio.monitoring import evaluator as monitoring_evaluator
from arp.portfolio.news.classifier import classify_article
from arp.schemas.portfolio import AggregationResult, AnalyticSpec, PivotSpec
from arp.schemas.portfolio_monitoring import AlertRule, AlertStatus, AlertTransition

portfolio_app = typer.Typer(help="Portfolio holdings aggregation, analytics, and NL Q&A.")


@portfolio_app.command("seed-demo")
def portfolio_seed_demo() -> None:
    """Seeds the built-in illustrative multi-portfolio demo dataset (see
    arp/portfolio/mock_data.py): companies, securities (incl. one
    deliberately unresolved instrument), 4 quarterly holdings snapshots
    across 4 portfolios, climate data-point observations with a validated
    internal-API/extraction cross-check, and ingested news items.
    Deterministic and safe to re-run.
    """
    settings = get_settings()
    store = _portfolio_store()
    policy = governance.get_current_policy(store, settings)
    summary = asyncio.run(
        generate_demo_dataset(store, policy["portfolio_confidence_review_threshold"], policy["climate_validation_tolerance_pct"])
    )
    typer.echo(json.dumps(summary.__dict__, indent=2))



@portfolio_app.command("list")
def portfolio_list() -> None:
    for p in _portfolio_store().list_portfolios():
        typer.echo(f"{p.portfolio_id}\t{p.name}\t{','.join(p.tags)}")



@portfolio_app.command("review-queue")
def portfolio_review_queue() -> None:
    """Securities whose issuer entity resolution fell below the confidence
    threshold -- never auto-matched, always surfaced here instead."""
    rows = _portfolio_store().list_resolutions_needing_review()
    if not rows:
        typer.echo("Nothing pending review.")
        return
    for r in rows:
        typer.echo(f"{r.security_id}\tbest_guess_company_id={r.company_id}\tconfidence={r.confidence:.2f}\tmethod={r.method}")



@portfolio_app.command("aggregate")
def portfolio_aggregate(
    group_by: str = typer.Option(..., help="portfolio_id | asset_class | company_id | company_name | sector | country | currency"),
    metric: str = typer.Option("market_value_sum", help="market_value_sum | weighted_avg_datapoint | count"),
    portfolio: list[str] = typer.Option(None, "--portfolio", help="Restrict to these portfolio_ids; repeatable."),
    company_id: str = typer.Option(None, help="Filter to one issuer, e.g. bmw."),
    asset_class: str = typer.Option(None),
    data_point_field_id: str = typer.Option(None, help="Required for metric=weighted_avg_datapoint, e.g. climate_carbon_intensity."),
    as_of: str = typer.Option(None, help="Snapshot date; defaults to the latest available."),
    name: str = typer.Option("cli query"),
) -> None:
    """Runs a query against the deterministic aggregation engine -- the
    same "how many EUR million exposure to BMW" primitive the API and the
    NL Q&A agent both use underneath."""
    store = _portfolio_store()
    security_filter: dict[str, str] = {}
    if company_id:
        security_filter["company_id"] = company_id
    if asset_class:
        security_filter["asset_class"] = asset_class
    spec = AnalyticSpec(
        name=name, portfolio_filter=portfolio or [], security_filter=security_filter, group_by=group_by,
        metric=metric, data_point_field_id=data_point_field_id, as_of=as_of,
    )
    securities, companies = _portfolio_directories(store)
    try:
        result = analytics.execute(spec, store, securities, companies)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if isinstance(result, AggregationResult):
        typer.echo(json.dumps(result.model_dump(mode="json"), indent=2))
    else:
        typer.echo(json.dumps([point.model_dump(mode="json") for point in result], indent=2))



@portfolio_app.command("pivot")
def portfolio_pivot(
    row_dim: str = typer.Option(..., help="portfolio_id | asset_class | company_id | company_name | sector | country | currency"),
    col_dim: str = typer.Option(..., help="Same choices as --row-dim."),
    metric: str = typer.Option("market_value_sum", help="market_value_sum | weighted_avg_datapoint | count"),
    portfolio: list[str] = typer.Option(None, "--portfolio", help="Restrict to these portfolio_ids; repeatable."),
    company_id: str = typer.Option(None, help="Filter to one issuer, e.g. bmw."),
    asset_class: str = typer.Option(None),
    data_point_field_id: str = typer.Option(None, help="Required for metric=weighted_avg_datapoint, e.g. climate_carbon_intensity."),
    as_of: str = typer.Option(None, help="Snapshot date; defaults to the latest available."),
    name: str = typer.Option("cli pivot"),
) -> None:
    """A two-dimension permutation of `arp portfolio aggregate` -- e.g.
    --row-dim sector --col-dim asset_class to see the whole exposure
    breakdown as a single cross-tab instead of one dimension at a time."""
    store = _portfolio_store()
    security_filter: dict[str, str] = {}
    if company_id:
        security_filter["company_id"] = company_id
    if asset_class:
        security_filter["asset_class"] = asset_class
    spec = PivotSpec(
        name=name, portfolio_filter=portfolio or [], security_filter=security_filter, row_dim=row_dim, col_dim=col_dim,
        metric=metric, data_point_field_id=data_point_field_id, as_of=as_of,
    )
    securities, companies = _portfolio_directories(store)
    try:
        result = analytics.execute_pivot(spec, store, securities, companies)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(result.model_dump(mode="json"), indent=2))



@portfolio_app.command("ask")
def portfolio_ask(question: str) -> None:
    """Answers a plain-language portfolio question end to end: the LLM
    only drafts a query, the deterministic engine computes it, and the
    printed answer shows the real numbers behind it. Requires
    ARP_ANTHROPIC_API_KEY."""
    llm = build_llm_client(get_settings())
    store = _portfolio_store()
    securities, companies = _portfolio_directories(store)
    answer, _usage = asyncio.run(qa_agent.answer_question(question, llm, store, securities, companies))
    if not answer.resolvable:
        typer.echo(f"Could not resolve the question: {answer.clarification_needed}")
        raise typer.Exit(1)
    typer.echo(answer.answer_text)



@portfolio_app.command("classify-news")
def portfolio_classify_news() -> None:
    """Runs the LLM risk classifier over ingested, not-yet-classified news
    items and persists any resulting grounded risk flags. Requires
    ARP_ANTHROPIC_API_KEY."""
    llm = build_llm_client(get_settings())
    store = _portfolio_store()
    already_classified = {f.news_id for f in store.list_flags()}
    pending = [item for item in store.list_news() if item.news_id not in already_classified]

    async def _run() -> int:
        created = 0
        for item in pending:
            flag, _usage = await classify_article(item, llm)
            if flag is not None:
                store.append_flag(flag)
                created += 1
        return created

    created = asyncio.run(_run())
    typer.echo(f"Classified {len(pending)} article(s), created {created} risk flag(s).")



@portfolio_app.command("monitoring-rules-list")
def portfolio_monitoring_rules_list() -> None:
    for r in _portfolio_store().list_rules():
        typer.echo(f"{r.rule_id}\t{r.name}\t{r.rule_type}\t{r.comparator} {r.threshold_value}\tenabled={r.enabled}")



@portfolio_app.command("monitoring-rules-add")
def portfolio_monitoring_rules_add(
    name: str = typer.Option(...),
    rule_type: str = typer.Option(..., help="field_threshold | concentration_threshold | portfolio_aggregate_threshold"),
    comparator: str = typer.Option(..., help="gt | gte | lt | lte"),
    threshold_value: float = typer.Option(...),
    field_id: str = typer.Option(None, help="Required for field_threshold/portfolio_aggregate_threshold, e.g. climate_carbon_intensity."),
    company_id: list[str] = typer.Option(None, "--company-id", help="Restrict to these company_ids; repeatable. Only used by field_threshold."),
    portfolio: list[str] = typer.Option(None, "--portfolio", help="Restrict to these portfolio_ids; repeatable."),
    severity: str = typer.Option("medium", help="low | medium | high"),
) -> None:
    """Adds a new threshold/breach rule for the continuous monitoring
    evaluator (see arp/portfolio/monitoring/evaluator.py)."""
    rule = AlertRule(
        name=name, rule_type=rule_type, field_id=field_id, comparator=comparator, threshold_value=threshold_value,
        company_ids=company_id or [], portfolio_ids=portfolio or [], severity=severity,
    )
    _portfolio_store().save_rule(rule)
    typer.echo(f"Created rule {rule.rule_id}")



@portfolio_app.command("monitoring-evaluate-now")
def portfolio_monitoring_evaluate_now() -> None:
    """Runs the same evaluation entrypoints the scheduler uses -- a manual
    pass useful for demos/testing without waiting for the interval."""
    store = _portfolio_store()
    settings = get_settings()
    threshold_alerts = monitoring_evaluator.evaluate_threshold_rules(store)
    news_alerts = monitoring_evaluator.evaluate_news_triggers(store, min_severity=settings.portfolio_monitoring_news_min_severity)
    typer.echo(f"Raised {len(threshold_alerts)} threshold alert(s), {len(news_alerts)} news alert(s).")



@portfolio_app.command("monitoring-alerts-list")
def portfolio_monitoring_alerts_list(status: str = typer.Option(None, help="Filter: open | acknowledged | escalated | resolved | false_positive")) -> None:
    alerts = monitoring_evaluator.list_alerts(_portfolio_store(), status=AlertStatus(status) if status else None)
    if not alerts:
        typer.echo("No alerts.")
        return
    for a in alerts:
        typer.echo(f"{a.scope_id}\t{a.alert_id}\t{a.category}\t{a.status}\t{a.breach_type}\t{a.rationale}")



@portfolio_app.command("monitoring-alerts-transition")
def portfolio_monitoring_alerts_transition(
    scope_id: str, alert_id: str, status: str = typer.Option(...), decided_by: str = typer.Option(...), reason: str = typer.Option("")
) -> None:
    """Records a human-decided status change for one alert -- decided_by
    is required, mirroring the escalation ladder's human checkpoint."""
    try:
        updated = monitoring_evaluator.transition_alert(
            _portfolio_store(), scope_id, alert_id, AlertTransition(status=AlertStatus(status), decided_by=decided_by, reason=reason)
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"{updated.alert_id} -> {updated.status}")
