from __future__ import annotations

from functools import lru_cache

from arp.agents.calibration_agent import CalibrationAgentScheduler
from arp.agents.taxonomy_researcher import TaxonomyResearcherScheduler
from arp.config import Settings, get_settings
from arp.discovery.scheduler import DiscoveryScheduler
from arp.discovery.site_finder import DuckDuckGoSearchClient, WebSearchClient
from arp.ingestion.edgar import EdgarDocumentSource
from arp.ingestion.local_files import LocalFileDocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient
from arp.llm.factory import build_llm_client
from arp.storage.document_store import DocumentContentStore
from arp.storage.engagement_store import EngagementStore
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore
from arp.voting.ballot_casting import BallotPlatform, ManualInstructionBallotPlatform


def settings_dep() -> Settings:
    return get_settings()


@lru_cache
def get_run_store() -> RunStore:
    return RunStore(get_settings().runs_dir)


@lru_cache
def get_taxonomy_store() -> TaxonomyStore:
    return TaxonomyStore(get_settings().taxonomies_dir)


@lru_cache
def get_portfolio_store() -> PortfolioStore:
    return PortfolioStore(get_settings().portfolios_dir)


@lru_cache
def get_document_content_store() -> DocumentContentStore:
    settings = get_settings()
    return DocumentContentStore(settings.document_store_dir, enabled=settings.document_cache_enabled)


@lru_cache
def get_registry() -> DocumentSourceRegistry:
    settings = get_settings()
    return DocumentSourceRegistry(
        [
            LocalFileDocumentSource(
                settings.documents_dir,
                content_store=get_document_content_store(),
                max_concurrent_parses=settings.max_concurrent_parses,
            ),
            EdgarDocumentSource(
                settings.edgar_user_agent,
                settings.cache_dir,
                content_store=get_document_content_store(),
                submissions_ttl_hours=settings.edgar_submissions_ttl_hours,
            ),
        ]
    )


@lru_cache
def get_edgar_source() -> EdgarDocumentSource:
    """Shared with get_registry()'s EdgarDocumentSource in every respect
    except this one isn't tied to DocumentSourceRegistry -- used directly
    by identity resolution (arp/discovery/identity_pipeline.py) for
    EdgarDocumentSource.search_by_name, not for fetching filings."""
    settings = get_settings()
    return EdgarDocumentSource(
        settings.edgar_user_agent,
        settings.cache_dir,
        content_store=get_document_content_store(),
        submissions_ttl_hours=settings.edgar_submissions_ttl_hours,
    )


@lru_cache
def get_web_search_client() -> WebSearchClient:
    return DuckDuckGoSearchClient(get_settings().discovery_user_agent)


def get_llm_client() -> LLMClient:
    """Not cached: constructing raises a clear error if no API key is
    configured, and we want that error surfaced per-request rather than
    baked into a cached singleton at import time.
    """
    return build_llm_client(get_settings())


@lru_cache
def get_scheduler() -> DiscoveryScheduler:
    return DiscoveryScheduler(get_settings(), get_run_store())


@lru_cache
def get_taxonomy_researcher_scheduler() -> TaxonomyResearcherScheduler:
    return TaxonomyResearcherScheduler(
        get_settings(), get_run_store(), get_taxonomy_store(), get_llm_client, get_web_search_client()
    )


@lru_cache
def get_calibration_scheduler() -> CalibrationAgentScheduler:
    return CalibrationAgentScheduler(get_settings(), get_run_store(), get_registry())


@lru_cache
def get_engagement_store() -> EngagementStore:
    return EngagementStore(get_settings().engagements_dir)


@lru_cache
def get_ballot_platform() -> BallotPlatform:
    return ManualInstructionBallotPlatform(get_settings().ballots_dir)
