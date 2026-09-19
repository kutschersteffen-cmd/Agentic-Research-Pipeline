from __future__ import annotations

import typer

from arp.config import get_settings
from arp.ingestion.edgar import EdgarDocumentSource
from arp.ingestion.indexing_config import IndexingConfig
from arp.ingestion.local_files import LocalFileDocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.ingestion.xbrl import XbrlFactSource
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import SecurityRef
from arp.schemas.taxonomy import TaxonomyRef
from arp.storage.document_store import DocumentContentStore
from arp.storage.engagement_store import EngagementStore
from arp.storage.portfolio_store import PortfolioStore
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
    return DocumentContentStore(settings.document_store_dir, enabled=settings.document_cache_enabled)



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



def _portfolio_directories(store: PortfolioStore) -> tuple[dict[str, SecurityRef], dict[str, CompanyRef]]:
    securities = {s.security_id: s for s in store.list_securities()}
    companies = {c.company_id: c for c in store.list_companies()}
    return securities, companies
