from __future__ import annotations

from arp.config import Settings
from arp.ingestion.indexing_config import IndexingConfig


def _settings(tmp_path, **overrides) -> Settings:
    return Settings(
        anthropic_api_key="unused",
        runs_dir=tmp_path / "runs",
        documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache",
        discovery_state_dir=tmp_path / "disc",
        portfolios_dir=tmp_path / "portfolios",
        document_store_dir=tmp_path / "docstore",
        **overrides,
    )


def test_from_settings_maps_every_field(tmp_path):
    settings = _settings(
        tmp_path,
        opensearch_url="http://localhost:9200",
        search_live_indexing_enabled=True,
        object_store_endpoint_url="http://localhost:9000",
        object_store_access_key="arp",
        object_store_secret_key="arp12345",
        object_store_bucket="arp-documents",
        object_store_live_upload_enabled=True,
    )

    config = IndexingConfig.from_settings(settings)

    assert config.opensearch_url == "http://localhost:9200"
    assert config.search_live_indexing_enabled is True
    assert config.object_store_endpoint_url == "http://localhost:9000"
    assert config.object_store_access_key == "arp"
    assert config.object_store_secret_key == "arp12345"
    assert config.object_store_bucket == "arp-documents"
    assert config.object_store_live_upload_enabled is True


def test_opensearch_enabled_requires_both_url_and_flag(tmp_path):
    assert not IndexingConfig(opensearch_url=None, search_live_indexing_enabled=True).opensearch_enabled
    assert not IndexingConfig(opensearch_url="http://localhost:9200", search_live_indexing_enabled=False).opensearch_enabled
    assert IndexingConfig(opensearch_url="http://localhost:9200", search_live_indexing_enabled=True).opensearch_enabled


def test_object_store_enabled_requires_both_url_and_flag(tmp_path):
    assert not IndexingConfig(object_store_endpoint_url=None, object_store_live_upload_enabled=True).object_store_enabled
    assert not IndexingConfig(object_store_endpoint_url="http://localhost:9000", object_store_live_upload_enabled=False).object_store_enabled
    assert IndexingConfig(
        object_store_endpoint_url="http://localhost:9000", object_store_live_upload_enabled=True
    ).object_store_enabled


def test_defaults_are_entirely_disabled():
    config = IndexingConfig()
    assert not config.opensearch_enabled
    assert not config.object_store_enabled
