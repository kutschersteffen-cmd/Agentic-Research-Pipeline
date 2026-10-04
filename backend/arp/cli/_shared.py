from __future__ import annotations

import os

import typer

from arp.api.auth import Principal, load_users
from arp.config import Settings, get_settings
from arp.ingestion.edgar import EdgarDocumentSource
from arp.ingestion.esef import EsefDocumentSource
from arp.ingestion.indexing_config import IndexingConfig
from arp.ingestion.local_files import LocalFileDocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.ingestion.xbrl import XbrlFactSource
from arp.retrieval.content_store_factory import content_store_for
from arp.schemas.taxonomy import TaxonomyRef
from arp.storage.document_store import DocumentContentStore
from arp.storage.engagement_store import EngagementStore
from arp.storage.portfolio_store import portfolio_directories
from arp.storage.portfolio_store_factory import build_portfolio_store
from arp.storage.postgres_projection_config import ProjectionConfig
from arp.storage.reporting_store import ReportingStore
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore
from arp.storage.topic_store import TopicStateStore
from arp.voting.ballot_casting import ManualInstructionBallotPlatform


def _engagement_store() -> EngagementStore:
    settings = get_settings()
    return EngagementStore(settings.engagements_dir, projection_config=ProjectionConfig.from_settings(settings))



def _reporting_store() -> ReportingStore:
    settings = get_settings()
    return ReportingStore(settings.reports_dir, settings.report_templates_dir)



def _ballot_platform() -> ManualInstructionBallotPlatform:
    return ManualInstructionBallotPlatform(get_settings().ballots_dir)



def _document_content_store() -> DocumentContentStore:
    settings = get_settings()
    return content_store_for(settings)



def _registry() -> DocumentSourceRegistry:
    settings = get_settings()
    indexing_config = IndexingConfig.from_settings(settings)
    return DocumentSourceRegistry(
        [
            LocalFileDocumentSource(
                settings.documents_dir,
                content_store=_document_content_store(),
                max_concurrent_parses=settings.max_concurrent_parses,
                indexing_config=indexing_config,
            ),
            EdgarDocumentSource(
                settings.edgar_user_agent,
                settings.cache_dir,
                content_store=_document_content_store(),
                submissions_ttl_hours=settings.edgar_submissions_ttl_hours,
                indexing_config=indexing_config,
            ),
            *([EsefDocumentSource(settings.esef_index_url, settings.cache_dir, content_store=_document_content_store(),
                                  indexing_config=indexing_config)] if settings.esef_enabled else []),
        ]
    )



def _xbrl_source() -> XbrlFactSource:
    settings = get_settings()
    edgar = EdgarDocumentSource(
        settings.edgar_user_agent, settings.cache_dir, content_store=_document_content_store(),
        submissions_ttl_hours=settings.edgar_submissions_ttl_hours,
    )
    return XbrlFactSource(edgar, settings.cache_dir, ttl_hours=settings.xbrl_facts_ttl_hours)



def _run_store() -> RunStore:
    settings = get_settings()
    return RunStore(settings.runs_dir, projection_config=ProjectionConfig.from_settings(settings))



def _taxonomy_store() -> TaxonomyStore:
    return TaxonomyStore(get_settings().taxonomies_dir)


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



def _topic_store() -> TopicStateStore:
    return TopicStateStore(get_settings().emerging_themes_state_dir / "topics")



def _portfolio_store():
    return build_portfolio_store(get_settings())



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
