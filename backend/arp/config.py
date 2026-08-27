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
    llm_verifier_model: str = Field(
        default="claude-opus-5",
        description="Model used for every independent Verifier/Kritiker call (extraction, financials), "
        "deliberately different from llm_model. An extractor and a verifier that run on the same model can "
        "repeat the same failure mode instead of catching it -- correlated errors the Advocate/Opposing/"
        "Adjudicator debate's differing prompts don't fix, because the underlying weights are identical. "
        "Set equal to llm_model to opt back into the old single-model behavior.",
    )
    llm_max_retries: int = Field(default=5)
    llm_cache_enabled: bool = Field(default=True)

    # Paths (all file-based storage lives under these)
    runs_dir: Path = Field(default=REPO_ROOT / "runs")
    taxonomies_dir: Path = Field(default=REPO_ROOT / "taxonomies")
    portfolios_dir: Path = Field(default=REPO_ROOT / "portfolios")
    documents_dir: Path = Field(default=REPO_ROOT / "data" / "documents")
    cache_dir: Path = Field(default=REPO_ROOT / "backend" / ".cache")
    document_store_dir: Path = Field(
        default=REPO_ROOT / "backend" / ".document_store",
        description="SQLite content-addressed cache of parsed document text; see arp.storage.document_store.",
    )
    discovery_state_dir: Path = Field(default=REPO_ROOT / "backend" / ".discovery_state")
    engagements_dir: Path = Field(default=REPO_ROOT / "engagements")
    ballots_dir: Path = Field(default=REPO_ROOT / "ballots", description="Where the manual-instruction ballot platform writes vote instruction files, absent a real custodian/proxy-platform integration.")

    # Batch / concurrency
    max_concurrent_llm_calls: int = Field(default=8)
    max_concurrent_downloads: int = Field(default=4)
    max_concurrent_parses: int = Field(
        default=4, description="Bounds concurrent off-loop document parses; the default executor allows 32."
    )

    document_cache_enabled: bool = Field(default=True)
    hybrid_retrieval_enabled: bool = Field(
        default=True,
        description="Adds a local-embedding vector ranking, fused with BM25 via reciprocal rank fusion, to "
        "select_relevant_chunks in the theme-matching and extraction/financials pipelines. On by default: BM25 "
        "alone misses vocabulary gaps between a field's seed keywords and how a company actually phrases a "
        "disclosure (e.g. 'e-mobility transition' vs. seed keyword 'electrification'), and the embedding model is "
        "multilingual (see arp/retrieval/embeddings.py) so this also covers DE-language disclosures the old "
        "English-only default couldn't meaningfully rank. Set false to fall back to pure BM25 (the old default), "
        "e.g. to reproduce prior runs exactly. Transition Plan Assessment intentionally stays BM25-only regardless "
        "of this flag -- see arp/transition_plan/indicator_graph.py -- to keep its replication of the source "
        "paper's retrieval behavior exact.",
    )

    # Precision controls
    grounding_fuzzy_threshold: float = Field(
        default=0.92, description="Min normalized similarity for a citation quote to count as grounded."
    )
    confidence_review_threshold: float = Field(
        default=0.6, description="Extractions/matches below this confidence are routed to the review queue."
    )

    # Engagement & voting stewardship module
    engagement_sla_days: int = Field(
        default=45, description="An open engagement issue with no recorded activity for this many days is flagged stalled."
    )
    fund_name: str | None = Field(
        default=None, description="Used by the Policy Application Agent to detect the fund's own co-filed shareholder resolutions."
    )

    # SEC EDGAR requires a descriptive User-Agent identifying the requester.
    edgar_user_agent: str = Field(default="Agentic Research Pipeline research@example.com")
    edgar_submissions_ttl_hours: float = Field(
        default=24.0, description="Filings list changes over time, so this cache (unlike the accession-keyed filing-document cache) expires."
    )
    xbrl_facts_enabled: bool = Field(
        default=True,
        description="Resolve CapEx/R&D totals for EDGAR filers directly from SEC's structured XBRL companyfacts API "
        "before running the LLM extractor on those figures -- what's already machine-readable is never estimated "
        "by an LLM. On by default: it's a free, no-key SEC endpoint with no configuration required, unlike the "
        "revenue/CapEx catalogue cascade (which needs a user-supplied file). Segment-level figures and CapEx/R&D "
        "descriptions still always go through the LLM pipeline -- XBRL tagging isn't standardized enough for those.",
    )
    xbrl_facts_ttl_hours: float = Field(default=24.0 * 7, description="companyfacts cache TTL -- lower churn than the filings-list cache.")

    # Indirect (input-output) exposure tier. Off by default -- requires an
    # ICIO-format industry x industry matrix; see docs/METHODOLOGY.md.
    icio_matrix_path: Path | None = Field(
        default=None, description="Path to an industry x industry intermediate-flows CSV. None disables this tier."
    )
    icio_industries_path: Path | None = Field(
        default=None, description="Path to the companion industries.csv (isic_code, label, total_output)."
    )
    icio_edition_label: str = Field(default="sample")
    indirect_exposure_review_threshold: float = Field(
        default=0.3, description="Structural exposure share above which a no-direct-evidence company is flagged."
    )

    # Standards mapping (NACE/NAICS/SIC/GICS). Each resolves independently
    # to a real, configured file; falls back to the bundled illustrative
    # sample only when --use-sample-standards is passed explicitly. NACE/
    # NAICS/SIC paths point at an official ISIC correspondence CSV
    # (isic_code,target_code,target_label); the GICS path points at a
    # sector/industry reference CSV (code,label,level) -- GICS structure
    # below sector level is MSCI/S&P-licensed, so it isn't bundled.
    nace_crosswalk_path: Path | None = Field(default=None, description="ISIC Rev.4 -> NACE Rev.2 correspondence CSV.")
    naics_crosswalk_path: Path | None = Field(default=None, description="ISIC Rev.4 -> NAICS correspondence CSV.")
    sic_crosswalk_path: Path | None = Field(default=None, description="ISIC Rev.4 -> SIC correspondence CSV.")
    gics_reference_path: Path | None = Field(default=None, description="GICS code/label/level reference CSV (requires a GICS license for the full structure).")

    # Revenue/CapEx exposure resolution (catalogue -> extraction -> qualitative
    # debate cascade). Thresholds mirror MSCI's published revenue-share bands.
    revenue_exposure_pure_play_threshold: float = Field(default=0.5)
    revenue_exposure_significant_threshold: float = Field(default=0.2)
    revenue_exposure_minor_threshold: float = Field(default=0.05)

    # Web discovery
    discovery_user_agent: str = Field(default="ARP-DiscoveryBot/0.1 (+research use; respects robots.txt)")
    discovery_webhook_url: str | None = Field(default=None)
    discovery_max_crawl_depth: int = Field(default=2)
    discovery_max_pages_per_company: int = Field(default=40)
    discovery_request_delay_seconds: float = Field(default=1.0)
    discovery_schedule_enabled: bool = Field(default=False)
    discovery_schedule_interval_hours: float = Field(default=24.0)
    discovery_schedule_universe_path: Path | None = Field(default=None)

    # Agentic company identity resolution (arp/discovery/identity_*.py) --
    # a separate enrichment run, not part of the discovery crawl above.
    identity_resolution_confidence_threshold: float = Field(
        default=0.7,
        description="Stricter than the general confidence_review_threshold: a wrong identity match is coherently "
        "wrong (well-cited documents about the wrong company) with no downstream mechanical check, unlike a "
        "citation grounding.py can catch.",
    )
    identity_resolution_max_search_results: int = Field(default=5)

    # Portfolio risk & exposure monitoring
    portfolio_confidence_review_threshold: float = Field(
        default=0.6, description="Security-to-issuer entity resolution matches below this confidence are routed to review."
    )
    climate_validation_tolerance_pct: float = Field(
        default=0.15, description="Disagreement between the internal ESG API and extracted-from-disclosures values beyond this share is flagged conflicting_sources."
    )

    # Optional Postgres/pgvector store (arp/storage/postgres*.py, requires
    # the `postgres` extra: pip install -e ".[postgres]"). Additive, not a
    # replacement for the file-based run/review audit trail: at this
    # system's scale (batch runs, one review queue per run, no concurrent
    # multi-writer access to the same record) an append-only JSONL history
    # is simpler to keep fully auditable than a table with UPDATEs. The
    # place a relational store earns its cost is Portfolio Risk & Exposure
    # Monitoring, where holdings need real joins across portfolios,
    # securities, companies, and time -- see docs/METHODOLOGY.md.
    postgres_dsn: str | None = Field(
        default=None,
        description="SQLAlchemy DSN, e.g. postgresql+psycopg://user:pass@host:5432/arp. None (default) disables "
        "every Postgres-backed feature below and the file-based stores behave exactly as before.",
    )
    portfolio_backend: str = Field(
        default="file",
        description="'file' (default, PortfolioStore) or 'postgres' (PostgresPortfolioStore, requires postgres_dsn) "
        "for portfolios/securities/companies/holdings-snapshots specifically. Observations/news/flags/analytics "
        "stay file-based either way -- see the module docstring in arp/storage/postgres_portfolio_store.py.",
    )
    embeddings_backend: str = Field(
        default="sqlite",
        description="'sqlite' (default, DocumentContentStore's local cache) or 'postgres' (pgvector, requires "
        "postgres_dsn) for the hybrid-retrieval chunk-embeddings cache. Same lookup/store interface either way, "
        "so hybrid_retrieval_enabled's behavior is unaffected -- only where the vectors are persisted changes.",
    )

    def ensure_dirs(self) -> None:
        for d in (
            self.runs_dir,
            self.taxonomies_dir,
            self.portfolios_dir,
            self.documents_dir,
            self.cache_dir,
            self.document_store_dir,
            self.discovery_state_dir,
            self.engagements_dir,
            self.ballots_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
