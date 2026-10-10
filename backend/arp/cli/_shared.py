from __future__ import annotations

import os

import typer

from arp.api import deps
from arp.api.auth import Principal, load_users
from arp.config import Settings, get_settings
from arp.ingestion.registry import DocumentSourceRegistry
from arp.schemas.taxonomy import TaxonomyRef
from arp.storage.portfolio_store import portfolio_directories
from arp.voting.ballot_casting import ManualInstructionBallotPlatform


async def _and_drain(coro):
    """Awaits `coro`, then every job it launched (event-driven refresh runs),
    so `asyncio.run` returning does not cancel them; prints their run ids."""
    from arp.orchestration.jobs import get_job_launcher

    result = await coro
    started = await get_job_launcher().drain()
    if started:
        typer.echo(f"Refresh runs started: {', '.join(started)}")
    return result


# The API's builders, uncached (__wrapped__): the CLI reads settings fresh on every call.
_engagement_store = deps.get_engagement_store.__wrapped__
_reporting_store = deps.get_reporting_store.__wrapped__


def _ballot_platform() -> ManualInstructionBallotPlatform:
    return ManualInstructionBallotPlatform(get_settings().ballots_dir)


_document_content_store = deps.get_document_content_store.__wrapped__


def _registry() -> DocumentSourceRegistry:
    return deps.build_registry(get_settings(), _document_content_store())


_xbrl_source = deps.get_xbrl_source.__wrapped__  # its EdgarDocumentSource is the cached get_edgar_source()
_run_store = deps.get_run_store.__wrapped__
_taxonomy_store = deps.get_taxonomy_store.__wrapped__


def _parse_taxonomy_ref(ref: str) -> TaxonomyRef:
    """Parses 'tax_xxx' or 'tax_xxx:3' (id, or id:version)."""
    if ":" in ref:
        taxonomy_id, version_str = ref.rsplit(":", 1)
        return TaxonomyRef(taxonomy_id=taxonomy_id, version=int(version_str))
    return TaxonomyRef(taxonomy_id=ref, version=None)


def _resolve_taxonomy_ref_or_exit(ref_str: str):
    store = _taxonomy_store()
    ref = _parse_taxonomy_ref(ref_str)
    taxonomy = store.get(ref.taxonomy_id, ref.version)
    if taxonomy is None:
        typer.echo(f"Taxonomy not found: {ref_str}", err=True)
        raise typer.Exit(1)
    return taxonomy


_topic_store = deps.get_topic_store.__wrapped__
_portfolio_store = deps.get_portfolio_store.__wrapped__
_portfolio_directories = portfolio_directories


def cli_principal(settings: Settings) -> Principal:
    """The signed-in user for CLI writes: env ARP_CLI_TOKEN looked up in the users file."""
    token = os.environ.get("ARP_CLI_TOKEN", "").strip()
    if not token:
        typer.echo("Set ARP_CLI_TOKEN to your user token (see config/users.example.json).", err=True)
        raise typer.Exit(1)
    try:
        user = load_users(settings.users_file).get(token)
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if user is None:
        typer.echo("ARP_CLI_TOKEN does not match any user.", err=True)
        raise typer.Exit(1)
    return user
