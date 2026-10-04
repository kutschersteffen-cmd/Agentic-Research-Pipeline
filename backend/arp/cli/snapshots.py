from __future__ import annotations

from pathlib import Path

import httpx
import typer

from arp.cli._shared import _portfolio_store
from arp.config import get_settings
from arp.snapshots.build import SnapshotFrozen, build_snapshot
from arp.snapshots.client import SnapshotClient, SnapshotHashMismatch

snapshots_app = typer.Typer(help="Build frozen monthly snapshots and pull them from another ARP instance (E77).")


@snapshots_app.command("build")
def build_cmd(as_of: str = typer.Option(..., "--as-of", help="The month end, e.g. 2026-10-31")) -> None:
    """Freezes the month's holdings and, when ARP_POSTGRES_DSN is set, its published ESG facts."""
    settings = get_settings()
    if settings.postgres_dsn:
        from arp.publish.facts import PublishStore
        from arp.publish.reader import facts_as_of

        store = PublishStore(settings.postgres_dsn)
        facts = lambda a: facts_as_of(store, a)  # noqa: E731
    else:
        typer.echo("ARP_POSTGRES_DSN is not set -- building without ESG facts.", err=True)
        facts = lambda a: []  # noqa: E731
    try:
        manifest = build_snapshot(as_of, root=settings.snapshot_store_dir, portfolio_store=_portfolio_store(),
                                  facts_as_of=facts)
    except (SnapshotFrozen, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(manifest.model_dump_json(indent=2))


@snapshots_app.command("pull")
def pull_cmd(
    month: str = typer.Option(..., "--month"),
    dataset: list[str] = typer.Option(["all"], "--dataset", help="Repeatable; 'all' for every dataset"),
    base_url: str | None = typer.Option(None, "--base-url"),
    dest: Path | None = typer.Option(None, "--dest"),
) -> None:
    """Pulls a month's latest frozen snapshot and verifies every file against the manifest."""
    settings = get_settings()
    base_url = base_url or settings.holdings_api_url
    if not base_url:
        typer.echo("Pass --base-url or set ARP_HOLDINGS_API_URL.", err=True)
        raise typer.Exit(1)
    client = None
    try:
        client = SnapshotClient(base_url, settings.holdings_api_token)
        paths = client.pull(month, "all" if dataset == ["all"] else dataset, dest or settings.snapshot_pull_dir)
    except (SnapshotHashMismatch, ValueError, httpx.HTTPError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    finally:
        if client is not None:
            client.close()
    for p in paths:
        typer.echo(str(p))
