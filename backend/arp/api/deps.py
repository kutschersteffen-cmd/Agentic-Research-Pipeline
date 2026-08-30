from __future__ import annotations

from functools import lru_cache

from arp.config import Settings, get_settings
from arp.discovery.scheduler import DiscoveryScheduler
from arp.discovery.site_finder import DuckDuckGoSearchClient, WebSearchClient
from arp.emerging_themes.scheduler import EmergingThemesScheduler
from arp.ingestion.edgar import EdgarDocumentSource
from arp.ingestion.local_files import LocalFileDocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.ingestion.xbrl import XbrlFactSource
from arp.llm.base import LLMClient
from arp.llm.factory import build_llm_client, build_verifier_llm_client
from arp.storage.document_store import DocumentContentStore
from arp.storage.engagement_store import EngagementStore
from arp.storage.portfolio_store_factory import build_portfolio_store
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore
from arp.storage.topic_store import TopicStateStore
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
def get_portfolio_store():
    return build_portfolio_store(get_settings())


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
def get_xbrl_source() -> XbrlFactSource:
    """CapEx/R&D totals resolved directly from SEC's structured XBRL
    companyfacts API, ahead of the LLM extraction pipeline for EDGAR
    filers -- see arp/ingestion/xbrl.py. Composes on the same
    EdgarDocumentSource instance get_edgar_source() already uses for CIK
    resolution, so no separate ticker-map fetch/cache is needed."""
    settings = get_settings()
    return XbrlFactSource(get_edgar_source(), settings.cache_dir, ttl_hours=settings.xbrl_facts_ttl_hours)


@lru_cache
def get_web_search_client() -> WebSearchClient:
    return DuckDuckGoSearchClient(get_settings().discovery_user_agent)


def get_llm_client() -> LLMClient:
    """Not cached: constructing raises a clear error if no API key is
    configured, and we want that error surfaced per-request rather than
    baked into a cached singleton at import time.
    """
    return build_llm_client(get_settings())


def get_verifier_llm_client() -> LLMClient:
    """The Verifier/Kritiker client, deliberately on a different model
    (settings.llm_verifier_model) than get_llm_client()'s extractor model
    -- see arp/llm/factory.py::build_verifier_llm_client."""
    return build_verifier_llm_client(get_settings())


@lru_cache
def get_scheduler() -> DiscoveryScheduler:
    return DiscoveryScheduler(get_settings(), get_run_store())


@lru_cache
def get_topic_store() -> TopicStateStore:
    return TopicStateStore(get_settings().emerging_themes_state_dir / "topics")


@lru_cache
def get_emerging_themes_scheduler() -> EmergingThemesScheduler:
    return EmergingThemesScheduler(get_settings(), get_run_store(), get_topic_store(), llm_factory=get_llm_client)


@lru_cache
def get_engagement_store() -> EngagementStore:
    return EngagementStore(get_settings().engagements_dir)


@lru_cache
def get_ballot_platform() -> BallotPlatform:
    return ManualInstructionBallotPlatform(get_settings().ballots_dir)
