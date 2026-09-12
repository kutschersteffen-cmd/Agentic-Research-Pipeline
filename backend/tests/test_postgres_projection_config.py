from __future__ import annotations

from arp.config import Settings
from arp.storage.postgres_projection_config import ProjectionConfig


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
        postgres_dsn="postgresql+psycopg://u:p@localhost/db",
        company_records_projection_enabled=True,
        company_facts_projection_enabled=True,
        engagement_projection_enabled=True,
    )
    config = ProjectionConfig.from_settings(settings)
    assert config.postgres_dsn == "postgresql+psycopg://u:p@localhost/db"
    assert config.company_records_projection_enabled is True
    assert config.company_facts_projection_enabled is True
    assert config.engagement_projection_enabled is True


def test_enabled_properties_require_both_dsn_and_flag():
    assert not ProjectionConfig(postgres_dsn=None, company_records_projection_enabled=True).company_records_enabled
    assert not ProjectionConfig(postgres_dsn="dsn", company_records_projection_enabled=False).company_records_enabled
    assert ProjectionConfig(postgres_dsn="dsn", company_records_projection_enabled=True).company_records_enabled

    assert not ProjectionConfig(postgres_dsn=None, company_facts_projection_enabled=True).company_facts_enabled
    assert ProjectionConfig(postgres_dsn="dsn", company_facts_projection_enabled=True).company_facts_enabled

    assert not ProjectionConfig(postgres_dsn=None, engagement_projection_enabled=True).engagement_enabled
    assert ProjectionConfig(postgres_dsn="dsn", engagement_projection_enabled=True).engagement_enabled


def test_defaults_are_entirely_disabled():
    config = ProjectionConfig()
    assert not config.company_records_enabled
    assert not config.company_facts_enabled
    assert not config.engagement_enabled
