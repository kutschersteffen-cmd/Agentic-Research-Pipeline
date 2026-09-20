from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.cli._shared import _document_content_store, _registry
from arp.schemas.common import CompanyRef, DocType
from arp.universe import load_company_universe

documents_app = typer.Typer(help="Operator surface for the document content cache (arp/storage/document_store.py).")


@documents_app.command("warm")
def documents_warm(
    universe: Path = typer.Option(..., help="Company universe JSON to warm the document cache for."),
    doc_types: str = typer.Option("", help="Comma-separated DocType values; empty = all supported types."),
    concurrency: int = typer.Option(4, help="Max companies fetched/parsed concurrently."),
) -> None:
    """Pays the fetch/parse cost for every company in a universe up
    front -- off-peak, before a batch run -- and surfaces any file that
    fails to parse now instead of mid-run. Safe to re-run: everything it
    touches is content-addressed, so an already-warm document is a fast
    cache hit rather than repeated work."""
    companies = load_company_universe(universe)
    types = [DocType(t.strip()) for t in doc_types.split(",") if t.strip()] or None
    registry = _registry()
    sem = asyncio.Semaphore(concurrency)
    failures: list[str] = []

    async def _warm_one(company: CompanyRef) -> int:
        async with sem:
            try:
                docs = await registry.fetch_all(company, types)
            except Exception as exc:  # noqa: BLE001 - isolate one company's failure from the rest
                failures.append(f"{company.company_id}: {exc}")
                return 0
        return len(docs)

    async def _run() -> list[int]:
        return await asyncio.gather(*(_warm_one(c) for c in companies))

    typer.echo(f"Warming document cache for {len(companies)} companies...")
    counts = asyncio.run(_run())
    typer.echo(f"Warmed {sum(counts)} documents across {len(companies)} companies.")
    if failures:
        typer.echo(f"{len(failures)} companies had errors:", err=True)
        for f in failures:
            typer.echo(f"  {f}", err=True)



@documents_app.command("cache-stats")
def documents_cache_stats() -> None:
    from arp.ingestion.edgar import _edgar_parser_version
    from arp.ingestion.local_files import parser_version

    stats = _document_content_store().stats()
    stats["current_local_parser_version"] = parser_version()
    stats["current_edgar_parser_version"] = _edgar_parser_version()
    typer.echo(json.dumps(stats, indent=2))



@documents_app.command("cache-prune")
def documents_cache_prune(yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt.")) -> None:
    """Deletes parsed_content rows stamped with a parser_version other
    than whatever's currently active (local file parsing and EDGAR
    extraction each have their own) and reclaims the freed space. Do not
    run this against a live API process -- VACUUM needs exclusive access
    to the database file."""
    from arp.ingestion.edgar import _edgar_parser_version
    from arp.ingestion.local_files import parser_version

    if not yes:
        typer.confirm(
            "This runs VACUUM and requires exclusive access to the document store -- "
            "make sure the API server is stopped. Continue?",
            abort=True,
        )
    current = [parser_version(), _edgar_parser_version()]
    deleted = _document_content_store().prune(keep_parser_version=current)
    typer.echo(f"Pruned {deleted} stale parsed_content row(s). Kept: {current}")
