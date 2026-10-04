from __future__ import annotations

import json
from dataclasses import asdict

import typer

from arp.api.auth import ROLE_RANK, Principal
from arp.cli._shared import _document_content_store, _run_store, cli_principal
from arp.config import Settings, get_settings
from arp.ingestion.indexing_config import IndexingConfig
from arp.publish.facts import ConcurrentPublish, PublishStore, public_release
from arp.publish.release import WithdrawalError, publish_run, withdraw
from arp.storage.document_blob_store import blob_store_for

publish_app = typer.Typer(help="Publish reviewed facts, withdraw releases, backfill old runs.")
CHECKPOINT = "published_facts"


def _approver(settings: Settings, what: str) -> Principal:
    principal = cli_principal(settings)
    if ROLE_RANK[principal.role] < ROLE_RANK["approver"]:
        typer.echo(f"{what} needs an approver", err=True)
        raise typer.Exit(1)
    return principal


def _store(settings: Settings) -> PublishStore:
    if not settings.postgres_dsn:
        typer.echo("ARP_POSTGRES_DSN is not set -- the published-fact store needs it.", err=True)
        raise typer.Exit(1)
    return PublishStore(settings.postgres_dsn)


def _publish(store, run_store, run_id, principal, settings):
    try:
        return publish_run(
            store, run_store, run_id, principal=principal,
            blob_store=blob_store_for(IndexingConfig.from_settings(settings)), content_store=_document_content_store(),
        )
    except ConcurrentPublish:
        typer.echo(
            f"run {run_id}: another publish changed these facts first; retry. "
            "Earlier documents of this run may already be published.", err=True,
        )
        raise typer.Exit(1) from None


@publish_app.command("run")
def publish_run_cmd(run_id: str = typer.Option(..., "--run-id")) -> None:
    """Publishes a run's final and auto-accepted values, one release per document."""
    settings = get_settings()
    principal = _approver(settings, "publishing")
    store, run_store = _store(settings), _run_store()
    if run_store.load_manifest(run_id) is None:
        typer.echo(f"unknown run {run_id}", err=True)
        raise typer.Exit(1)
    result = _publish(store, run_store, run_id, principal, settings)
    typer.echo(json.dumps({
        "releases": [public_release(r) for r in result.releases], "reconfirmed": result.reconfirmed,
        "blocked": result.blocked, "skipped": [asdict(s) for s in result.skipped],
    }, indent=2))


@publish_app.command("withdraw")
def withdraw_cmd(release_id: str = typer.Option(..., "--release-id"), reason: str = typer.Option(..., "--reason")) -> None:
    """Withdraws a release and restores each fact's previous value."""
    settings = get_settings()
    principal = _approver(settings, "withdrawing")
    reason = reason.strip()
    if not reason or len(reason) > 2000:
        typer.echo("--reason must be 1 to 2000 characters", err=True)
        raise typer.Exit(1)
    try:
        restored = withdraw(_store(settings), release_id, reason=reason, principal=principal)
    except (LookupError, WithdrawalError, ConcurrentPublish) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps({"restored": [f.model_dump(mode="json") for f in restored]}, indent=2))


@publish_app.command("backfill")
def backfill(full: bool = typer.Option(False, "--full", help="Every run, not only those changed since the last backfill.")) -> None:
    """Publishes old extraction runs as the system (E17). Incremental through a checkpoint."""
    from arp.schemas.common import now_iso
    from arp.storage.postgres_checkpoints import get_checkpoint, set_checkpoint

    settings = get_settings()
    store, run_store = _store(settings), _run_store()
    since = None if full else get_checkpoint(settings.postgres_dsn, CHECKPOINT)
    started_at = now_iso()  # recorded before reading, as the reindex commands do
    runs = sorted(
        (m for m in run_store.list_runs("extraction")
         if not m.params.get("trial") and (since is None or m.updated_at > since)),
        key=lambda m: m.created_at,
    )
    releases = reconfirmed = blocked = skipped = 0
    for m in runs:
        result = _publish(store, run_store, m.run_id, None, settings)
        releases += len(result.releases)
        reconfirmed += result.reconfirmed
        blocked += len(result.blocked)
        skipped += len(result.skipped)
    set_checkpoint(settings.postgres_dsn, CHECKPOINT, started_at)
    typer.echo(f"releases={releases} reconfirmed={reconfirmed} blocked={blocked} skipped={skipped}")
