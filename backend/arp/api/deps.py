from __future__ import annotations

from functools import lru_cache

from arp.config import Settings, get_settings
from arp.discovery.scheduler import DiscoveryScheduler
from arp.ingestion.edgar import EdgarDocumentSource
from arp.ingestion.local_files import LocalFileDocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.llm.base import LLMClient
from arp.llm.factory import build_llm_client
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore


def settings_dep() -> Settings:
    return get_settings()


@lru_cache
def get_run_store() -> RunStore:
    return RunStore(get_settings().runs_dir)


@lru_cache
def get_taxonomy_store() -> TaxonomyStore:
    return TaxonomyStore(get_settings().taxonomies_dir)


@lru_cache
def get_registry() -> DocumentSourceRegistry:
    settings = get_settings()
    return DocumentSourceRegistry(
        [
            LocalFileDocumentSource(settings.documents_dir),
            EdgarDocumentSource(settings.edgar_user_agent, settings.cache_dir),
        ]
    )


def get_llm_client() -> LLMClient:
    """Not cached: constructing raises a clear error if no API key is
    configured, and we want that error surfaced per-request rather than
    baked into a cached singleton at import time.
    """
    return build_llm_client(get_settings())


@lru_cache
def get_scheduler() -> DiscoveryScheduler:
    return DiscoveryScheduler(get_settings(), get_run_store())
