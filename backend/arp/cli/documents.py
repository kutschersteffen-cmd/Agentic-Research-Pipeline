from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from arp.cli._shared import _document_content_store, _registry, _run_store
from arp.config import get_settings
from arp.research.funnel import chunks_for, passage_vectors
from arp.research.match_graph import _funnel_content_store
from arp.retrieval.embeddings import EMBED_MODEL_NAME
from arp.schemas.common import CompanyRef, DocType
from arp.universe import load_company_universe

documents_app = typer.Typer(help="Operator surface for the document content cache (arp/storage/document_store.py).")


@documents_app.command("warm")
def documents_warm(
    universe: Path = typer.Option(..., help="Company universe JSON to warm the document cache for."),
    doc_types: str = typer.Option("", help="Comma-separated DocType values; empty = all supported types."),
    concurrency: int = typer.Option(4, help="Max companies fetched/parsed concurrently."),
    embed: bool = typer.Option(
        False, "--embed/--no-embed", help="Also store every chunk's embedding for the theme funnel (needs Postgres)."
    ),
) -> None:
    """Pays the fetch/parse cost for every company in a universe up
    front -- off-peak, before a batch run -- and surfaces any file that
    fails to parse now instead of mid-run. Safe to re-run: everything it
    touches is content-addressed, so an already-warm document is a fast
    cache hit rather than repeated work."""
    store = _funnel_content_store(get_settings()) if embed else None
    if embed and store is None:
        typer.echo("--embed needs ARP_POSTGRES_DSN (embeddings are stored in Postgres).", err=True)
        raise typer.Exit(1)
    companies = load_company_universe(universe)
    types = [DocType(t.strip()) for t in doc_types.split(",") if t.strip()] or None
    registry = _registry()
    sem = asyncio.Semaphore(concurrency)
    failures: list[str] = []
    embedded = {"new": 0, "stored": 0}

    async def _warm_one(company: CompanyRef) -> int:
        async with sem:
            try:
                docs = await registry.fetch_all(company, types)
            except Exception as exc:  # noqa: BLE001 - isolate one company's failure from the rest
                failures.append(f"{company.company_id}: {exc}")
                return 0
        if store is not None:  # sync and outside the semaphore: one company's chunks embed at a time
            try:
                chunks = chunks_for(docs)
                known = len(store.lookup_embeddings([c.chunk_id for c in chunks], EMBED_MODEL_NAME))
                passage_vectors(chunks, store)
            except Exception as exc:  # noqa: BLE001 - isolate one company's failure from the rest
                failures.append(f"{company.company_id}: embedding: {exc}")
                return len(docs)
            embedded["new"] += len(chunks) - known
            embedded["stored"] += known
        return len(docs)

    async def _run() -> list[int]:
        return await asyncio.gather(*(_warm_one(c) for c in companies))

    typer.echo(f"Warming document cache for {len(companies)} companies...")
    counts = asyncio.run(_run())
    typer.echo(f"Warmed {sum(counts)} documents across {len(companies)} companies.")
    if store is not None:
        typer.echo(f"Embedded {embedded['new']} new chunks ({embedded['stored']} already stored).")
    if failures:
        typer.echo(f"{len(failures)} companies had errors:", err=True)
        for f in failures:
            typer.echo(f"  {f}", err=True)



@documents_app.command("tree")
def documents_tree(
    doc_id: str = typer.Argument(..., help="Document whose stored tree to print."),
    as_json: bool = typer.Option(False, "--json", help="Print the stored tree as JSON."),
) -> None:
    """Prints the stored document tree (built at fetch with ARP_DOC_TREE_ENABLED=true), one node per line."""
    from arp.config import get_settings
    from arp.ingestion.doc_tree import dumps, format_tree, stored_tree

    tree = stored_tree(doc_id, get_settings())
    if tree is None:
        typer.echo(f"No tree stored for {doc_id}.", err=True)
        raise typer.Exit(1)
    typer.echo(dumps(tree) if as_json else "\n".join(format_tree(tree)))


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


@documents_app.command("reground")
def documents_reground(
    force: bool = typer.Option(False, "--force", help="Re-ground even if the parser version is unchanged."),
) -> None:
    """Re-grounds stored extraction citations parsed under an older parser
    version; moved or lost spans go to review (E51). Without --force, only
    when the parser version differs from the last recorded one."""
    from arp.config import get_settings
    from arp.ingestion.indexing_config import IndexingConfig
    from arp.orchestration.reground import reground_if_parser_changed, reground_runs
    from arp.storage.document_blob_store import blob_store_for

    settings = get_settings()
    stores = {"blob_store": blob_store_for(IndexingConfig.from_settings(settings)),
              "content_store": _document_content_store()}
    if force:
        report = reground_runs(_run_store(), settings=settings, **stores)
    else:
        report = reground_if_parser_changed(_run_store(), settings=settings, **stores)
    typer.echo("Parser version unchanged; nothing to re-ground." if report is None else str(report))
