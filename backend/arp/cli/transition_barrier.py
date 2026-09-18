from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.cli._shared import _run_store
from arp.config import get_settings
from arp.schemas.transition_barrier import Pillar, Region
from arp.transition_barrier.dataset import (
    filter_scores,
    load_criteria,
    load_source_registry,
    rating_distribution,
    sources_for_criterion,
)
from arp.transition_barrier.refresh.pipeline import RefreshDisabledError, run_refresh
from arp.transition_barrier.refresh.router import coverage_summary, route_sources
from arp.transition_barrier.staleness import build_staleness_report

transition_barrier_app = typer.Typer(
    help="Transition Barrier Assessment: the 105-cell sector x region transition-feasibility matrix (35 criteria x EU/US/China)."
)


@transition_barrier_app.command("criteria")
def transition_barrier_criteria(
    sector: str = typer.Option(None, help="Filter to one sector, e.g. 'Steel'."),
    pillar: Pillar = typer.Option(None, help="Filter to one constraint pillar."),
    out: Path = typer.Option(None, help="Write the criteria as JSON here; omit to print a summary."),
) -> None:
    """List the 35 criteria with their metrics and H/M/L rubrics."""
    criteria = load_criteria()
    if sector:
        criteria = [c for c in criteria if c.sector == sector]
    if pillar:
        criteria = [c for c in criteria if c.category is pillar]
    if out:
        out.write_text(json.dumps([c.model_dump(mode="json") for c in criteria], indent=2))
        typer.echo(f"Wrote {len(criteria)} criteria to {out}")
        return
    for c in criteria:
        typer.echo(f"{c.code}  [{c.sector} / {c.category.value}]  {c.criterion}  ({c.unit})")
    typer.echo(f"\n{len(criteria)} criteria")


@transition_barrier_app.command("scores")
def transition_barrier_scores(
    sector: str = typer.Option(None, help="Filter to one sector."),
    region: Region = typer.Option(None, help="Filter to one region."),
    pillar: Pillar = typer.Option(None, help="Filter to one constraint pillar."),
    rating: str = typer.Option(None, help="Filter to one rating: H, M or L."),
    out: Path = typer.Option(None, help="Write the matching cells as JSON here."),
) -> None:
    """Query the 105-cell matrix. H means transition is more feasible."""
    rows = filter_scores(sector=sector, region=region, pillar=pillar, rating=rating)
    if out:
        out.write_text(json.dumps([r.model_dump(mode="json") for r in rows], indent=2))
        typer.echo(f"Wrote {len(rows)} cells to {out}")
        return
    for r in rows:
        typer.echo(f"{r.code:<8} {r.region.value:<15} {r.rating.value}  (confidence: {r.confidence.value})  {r.criterion}")
    typer.echo(f"\n{len(rows)} cells | distribution across the full matrix: {rating_distribution()}")


@transition_barrier_app.command("sources")
def transition_barrier_sources(
    code: str = typer.Option(None, help="Show only sources backing this criterion, e.g. 'OGU-R1'."),
    access_pattern: str = typer.Option(None, help="Filter by access pattern, e.g. 'legal_regulatory_text'."),
    out: Path = typer.Option(None, help="Write the matching sources as JSON here."),
) -> None:
    """List the 86 deduplicated sources behind the matrix."""
    sources = sources_for_criterion(code) if code else load_source_registry()
    if access_pattern:
        sources = [s for s in sources if s.access_pattern.value == access_pattern]
    if out:
        out.write_text(json.dumps([s.model_dump(mode="json") for s in sources], indent=2))
        typer.echo(f"Wrote {len(sources)} sources to {out}")
        return
    for s in sources:
        typer.echo(f"[{s.access_pattern.value}] {s.source_name} ({s.publisher}) -> {s.url or 'no fixed URL'}")
    typer.echo(f"\n{len(sources)} sources")


@transition_barrier_app.command("staleness")
def transition_barrier_staleness(
    threshold_days: int = typer.Option(None, help="Override the staleness threshold (default: 548 days / 18 months)."),
) -> None:
    """Report which cells are overdue for re-verification.

    Staleness is independent of confidence: a high-confidence rating that has
    not been re-checked in 18 months is stale, not low-confidence.
    """
    settings = get_settings()
    report = build_staleness_report(threshold_days=threshold_days or settings.transition_barrier_staleness_days)
    typer.echo(f"Threshold: {report.threshold_days} days")
    typer.echo(f"{report.stale} of {report.total} cells stale, {report.fresh} fresh")
    if report.stale_codes:
        typer.echo(f"Stale criteria: {', '.join(report.stale_codes)}")


@transition_barrier_app.command("coverage")
def transition_barrier_coverage() -> None:
    """Show how much of the source registry the refresh pipeline can automate."""
    summary = coverage_summary()
    typer.echo(f"{summary['automatable']} of {summary['total_sources']} sources are automatable in this slice.")
    typer.echo(f"{summary['manual']} still require manual verification:\n")
    for routed in route_sources():
        if not routed.automatable:
            typer.echo(f"  {routed.source.key}: {routed.reason}")


@transition_barrier_app.command("refresh")
def transition_barrier_refresh() -> None:
    """Re-check the EUR-Lex legal sources against the recorded ratings.

    Never rewrites a rating. Anything that looks like a rating change is
    queued for human review; only evidence text and last_verified may ever be
    refreshed automatically, and only when the rating is unchanged.
    """
    settings = get_settings()
    try:
        run_id, findings = asyncio.run(run_refresh(settings=settings, run_store=_run_store()))
    except RefreshDisabledError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    needs_review = [f for f in findings if f.needs_review]
    typer.echo(f"Run complete: {run_id} (see runs/{run_id}/)")
    typer.echo(f"{len(findings)} checks, {len(needs_review)} queued for human review.")
    for finding in needs_review:
        typer.echo(f"  [{finding.outcome.value}] {finding.code} / {finding.region.value}: {finding.detail}")
