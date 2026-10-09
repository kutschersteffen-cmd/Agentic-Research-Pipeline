from __future__ import annotations

import asyncio
from collections import Counter
from functools import partial
from pathlib import Path

import httpx
import typer

from arp.cli._shared import _run_store
from arp.config import get_settings
from arp.universe import load_company_universe
from arp.xbrl_pipeline.fetch import build_source, create_xbrl_run, execute_xbrl_run
from arp.xbrl_pipeline.registry import TAXONOMY_SOURCES, TaxonomyRegistry, http_fetch, update_taxonomies
from arp.xbrl_pipeline.selection import cut_selection, parse_tag_ids
from arp.xbrl_pipeline.store import XbrlStore
from arp.xbrl_pipeline.verify import CircularRunError, UnsupportedRunError, assert_xbrl_off, verify_run

xbrl_app = typer.Typer(help="XBRL fact pipeline: fetch SEC company facts or EU ESEF filings, browse tags, cut selections, verify runs.")
taxonomy_app = typer.Typer(help="Official XBRL taxonomy registry.")
xbrl_app.add_typer(taxonomy_app, name="taxonomy")


def _store() -> XbrlStore:
    return XbrlStore(get_settings().xbrl_dir)


def _split(text: str) -> list[str]:
    return [t.strip() for t in text.split(",") if t.strip()]


def _validate_tags(tag_list: list[str]) -> frozenset[str]:
    try:
        return parse_tag_ids(tag_list)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


@xbrl_app.command("fetch")
def fetch(
    universe: Path = typer.Option(...),
    tags: str = typer.Option("", help="Comma-separated tags (us-gaap:Revenues,...); empty = mode All, keep every tag."),
    refresh: bool = typer.Option(False, help="Bypass the facts cache and re-download."),
    market: str = typer.Option("sec", help="sec (SEC company facts) or esef (EU ESEF filings)."),
) -> None:
    if market not in ("sec", "esef"):
        typer.echo(f"--market must be sec or esef, got {market!r}", err=True)
        raise typer.Exit(2)
    settings = get_settings()
    companies = load_company_universe(universe)
    tag_list = _split(tags) or None
    if tag_list:
        _validate_tags(tag_list)
    run_store = _run_store()
    run_id = create_xbrl_run(companies, tag_list, refresh, run_store, market=market)
    asyncio.run(execute_xbrl_run(
        run_id, companies, settings=settings, run_store=run_store, tags=tag_list, refresh=refresh,
        market=market, source=build_source(settings, refresh=refresh) if market == "sec" else None,
    ))
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    counts = Counter(r["status"] for r in rows)
    typer.echo("  ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "no companies fetched")
    typer.echo(f"Run: {run_id}")


@taxonomy_app.command("update")
def taxonomy_update() -> None:
    """Download the official taxonomies and refresh the local tag registry."""
    fetcher = partial(http_fetch, user_agent=get_settings().edgar_user_agent)
    try:
        written = asyncio.run(update_taxonomies(_store(), fetch=fetcher))
    except httpx.HTTPStatusError as exc:
        typer.echo(f"taxonomy download failed: HTTP {exc.response.status_code} for {exc.request.url}", err=True)
        raise typer.Exit(1) from exc
    except (httpx.HTTPError, ValueError) as exc:
        typer.echo(f"taxonomy update failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    for name in TAXONOMY_SOURCES:
        if name in written:
            typer.echo(f"{name}: {written[name]} tag(s)")


@xbrl_app.command("tags")
def tags(
    search: str = typer.Option("", help="Substring of concept name or label."),
    taxonomy: str | None = typer.Option(None),
    seen_only: bool = typer.Option(False, help="Only tags seen in fetched companies."),
    limit: int = typer.Option(50),
) -> None:
    entries, total = TaxonomyRegistry(_store()).search(search, taxonomy=taxonomy, seen_only=seen_only, limit=limit)
    for e in entries:
        typer.echo(f"{e.tag_id}  seen={e.seen_count}  {e.label or ''}".rstrip())
    typer.echo(f"{len(entries)} of {total} tag(s)" if len(entries) != total else f"{total} tag(s)")


@xbrl_app.command("select")
def select(
    name: str = typer.Option(...),
    tags: str = typer.Option(..., help="Comma-separated tags to cut out of the stored originals."),
) -> None:
    tag_set = _validate_tags(_split(tags))
    count = cut_selection(_store(), name, tag_set)
    typer.echo(f"Selection '{name}': {count} fact(s) across {len(tag_set)} tag(s)")


@xbrl_app.command("files")
def files(limit: int = typer.Option(50)) -> None:
    from arp.xbrl_pipeline.views import list_company_files

    items, total = list_company_files(_store(), limit=limit)
    for f in items:
        report = f"{f.report.form} {f.report.filing_date}" if f.report else "none"
        typer.echo(f"{f.cik}  {f.company_id}  {f.name or ''}  facts={f.fact_count}  report={report}")
    typer.echo(f"{len(items)} of {total} company file(s)" if len(items) != total else f"{total} company file(s)")


@xbrl_app.command("verify")
def verify(
    run_id: str = typer.Argument(...),
    map_: list[str] = typer.Option([], "--map", help="metric=field_id, e.g. revenue=revenue_total; repeatable."),
    tolerance: float = typer.Option(0.005, help="Relative tolerance for a match."),
) -> None:
    run_store = _run_store()
    try:
        assert_xbrl_off(run_id, run_store=run_store)  # the guard always reports first
    except ValueError as exc:  # CircularRunError, or a malformed step_settings.json
        typer.echo(f"{exc}" if isinstance(exc, CircularRunError) else f"{run_id}: cannot verify: {exc}", err=True)
        raise typer.Exit(1) from exc
    if not map_:
        typer.echo("pass at least one --map metric=field (e.g. --map revenue=revenue_total)", err=True)
        raise typer.Exit(2)
    mapping: dict[str, str] = {}
    for item in map_:
        metric, sep, field_id = item.partition("=")
        if not sep or not metric.strip() or not field_id.strip():
            typer.echo(f"--map must look like metric=field, got {item!r}", err=True)
            raise typer.Exit(2)
        mapping[metric.strip()] = field_id.strip()
    try:
        rows = verify_run(run_id, run_store=run_store, store=_store(), mapping=mapping, tolerance=tolerance)
    except UnsupportedRunError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    counts = Counter(r.outcome for r in rows)
    typer.echo(f"{len(rows)} comparison(s): " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
