from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Central runtime configuration, loaded from environment / .env."""

    model_config = SettingsConfigDict(env_prefix="ARP_", env_file=".env", extra="ignore")

    # LLM
    anthropic_api_key: str | None = Field(default=None)
    llm_model: str = Field(default="claude-sonnet-5")
    llm_max_retries: int = Field(default=5)
    llm_cache_enabled: bool = Field(default=True)

    # Paths (all file-based storage lives under these)
    runs_dir: Path = Field(default=REPO_ROOT / "runs")
    documents_dir: Path = Field(default=REPO_ROOT / "data" / "documents")
    cache_dir: Path = Field(default=REPO_ROOT / "backend" / ".cache")
    discovery_state_dir: Path = Field(default=REPO_ROOT / "backend" / ".discovery_state")

    # Batch / concurrency
    max_concurrent_llm_calls: int = Field(default=8)
    max_concurrent_downloads: int = Field(default=4)

    # Precision controls
    grounding_fuzzy_threshold: float = Field(
        default=0.92, description="Min normalized similarity for a citation quote to count as grounded."
    )
    confidence_review_threshold: float = Field(
        default=0.6, description="Extractions/matches below this confidence are routed to the review queue."
    )

    # SEC EDGAR requires a descriptive User-Agent identifying the requester.
    edgar_user_agent: str = Field(default="Agentic Research Pipeline research@example.com")

    # Web discovery
    discovery_user_agent: str = Field(default="ARP-DiscoveryBot/0.1 (+research use; respects robots.txt)")
    discovery_webhook_url: str | None = Field(default=None)
    discovery_max_crawl_depth: int = Field(default=2)
    discovery_max_pages_per_company: int = Field(default=40)
    discovery_request_delay_seconds: float = Field(default=1.0)
    discovery_schedule_enabled: bool = Field(default=False)
    discovery_schedule_interval_hours: float = Field(default=24.0)
    discovery_schedule_universe_path: Path | None = Field(default=None)

    def ensure_dirs(self) -> None:
        for d in (self.runs_dir, self.documents_dir, self.cache_dir, self.discovery_state_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
