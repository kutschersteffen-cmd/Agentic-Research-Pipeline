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
    llm_prompt_cache_enabled: bool = Field(
        default=True,
        description="Anthropic server-side prompt caching (distinct from llm_cache_enabled's disk cache). "
        "Tags the system prompt + tool schema as a 1h-TTL cache breakpoint on every call -- safe to enable "
        "broadly since every agent's system prompt is a fixed constant per call site; below the model's "
        "cacheable-prefix minimum it's a documented no-op, not a wasted write.",
    )

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
    reports_dir: Path = Field(default=REPO_ROOT / "reports", description="Presentation/Reporting Tool: one directory per generated report (manifest, request, plan, rendered output file).")
    report_templates_dir: Path = Field(default=REPO_ROOT / "report_templates", description="Presentation/Reporting Tool: ingested .pptx template style profiles + the original template file each is cloned from.")

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
    require_ratified_taxonomy: bool = Field(
        default=False,
        description="Human curation gate for theme runs (spec Step 0d): when true, POST /api/themes/runs refuses "
        "a taxonomy_id whose latest/selected version is still DRAFT. Off by default to preserve today's "
        "iterate-on-a-draft workflow; see arp.storage.taxonomy_store.ensure_taxonomy_usable_for_run.",
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

    # EXIOBASE input-output source (sibling to the ICIO tier above -- a run
    # is backed by at most one, see
    # arp.research.indirect_exposure.factory.resolve_indirect_exposure_model).
    # Off by default, same opt-in contract as the ICIO tier.
    exiobase_flows_path: Path | None = Field(
        default=None,
        description="Path to a long-format EXIOBASE-derived intermediate-flows CSV (required columns: "
        "supplier_isic_code, user_isic_code, value -- any other columns, e.g. region, are permitted and "
        "summed/collapsed over). Requires the caller to have already mapped EXIOBASE's native product/sector "
        "classification to ISIC Rev.4 division codes; that crosswalk is not attempted by this loader. None "
        "disables this source; see arp.research.indirect_exposure.exiobase_loader.",
    )
    exiobase_industries_path: Path | None = Field(
        default=None,
        description="Companion industries.csv for the EXIOBASE source -- same isic_code,label,total_output "
        "format as icio_industries_path; total_output must already be aggregated across regions by the caller.",
    )
    exiobase_edition_label: str = Field(default="exiobase-sample")

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

    # Cross-method arbitration (Step 4): a weighted composite ranking score
    # layered on top of exposure_estimate/revenue_exposure/indirect_exposure/
    # rd_exposure, never blending into or overwriting them -- see
    # arp.research.arbitration and docs/METHODOLOGY.md. Defaults are
    # documented, reasonable starting points, not empirically tuned against
    # a labeled eval set.
    arbitration_disagreement_threshold: float = Field(
        default=0.4, description="Included signals spanning more than this (0-1) are flagged as disagreeing rather than silently averaged."
    )
    arbitration_mid_band_low: float = Field(default=0.3, description="Composite scores in [low, high] are routed for review.")
    arbitration_mid_band_high: float = Field(default=0.7)
    arbitration_weight_qualitative_debate: float = Field(default=0.6, description="Weight for the Advocate/Opposing/Adjudicator debate's exposure_estimate.")
    arbitration_weight_revenue_catalogue: float = Field(default=1.0, description="Weight for a deterministic, user-supplied revenue-catalogue hit.")
    arbitration_weight_revenue_extracted: float = Field(default=0.8, description="Weight for an LLM-extracted, grounded revenue percentage.")
    arbitration_weight_indirect: float = Field(default=0.3, description="Weight for the sector-level input-output structural exposure signal.")
    arbitration_weight_rd_intensity: float = Field(default=0.5, description="Weight for Method C's extracted R&D-intensity signal.")
    arbitration_weight_news_mentions: float = Field(default=0.2, description="Weight for Method C's web-search news-mention signal (the weakest/noisiest).")

    # Web discovery
    discovery_user_agent: str = Field(default="ARP-DiscoveryBot/0.1 (+research use; respects robots.txt)")
    discovery_webhook_url: str | None = Field(default=None)
    discovery_max_crawl_depth: int = Field(default=2)
    discovery_max_pages_per_company: int = Field(default=40)
    discovery_request_delay_seconds: float = Field(default=1.0)
    discovery_schedule_enabled: bool = Field(default=False)
    discovery_schedule_interval_hours: float = Field(default=24.0)
    discovery_schedule_universe_path: Path | None = Field(default=None)

    # Emerging Themes Scanner ("Tool 0" -- arp/emerging_themes/). Ingests
    # public news/filings/regulatory flow across a universe, clusters it
    # with lineage tracking, and proposes bottom-up candidate themes into
    # the taxonomy DRAFT/ratify workflow. Requires the `emerging_themes`
    # extra (pip install -e ".[emerging_themes]").
    emerging_themes_state_dir: Path = Field(default=REPO_ROOT / "backend" / ".emerging_themes_state")
    emerging_themes_schedule_enabled: bool = Field(default=False)
    emerging_themes_schedule_interval_hours: float = Field(
        default=168.0, description="Weekly by default -- matches the lineage-tracking window the Detect layer links periods across."
    )
    emerging_themes_schedule_universe_path: Path | None = Field(default=None)
    emerging_themes_lookback_days: int = Field(default=14, description="How far back each Ingest pass looks for new mentions.")
    emerging_themes_min_independent_sources: int = Field(
        default=2, description="A cluster needs at least this many distinct source URLs before it can become a candidate."
    )
    emerging_themes_cluster_stability_reruns: int = Field(
        default=3, description="Reseeded UMAP/HDBSCAN reruns for the pre-LLM cluster-stability gate; a cluster must survive most of them."
    )
    emerging_themes_min_cluster_size: int = Field(default=3, description="HDBSCAN min_cluster_size.")
    emerging_themes_gdelt_max_records: int = Field(default=75, description="Per-query cap on GDELT DOC 2.0 API results.")

    # Standing background agents (arp/agents/) -- both clone
    # discovery/scheduler.py's AsyncIOScheduler + JSON-persisted-config
    # pattern exactly. Never auto-apply anything: Taxonomy Researcher only
    # ever writes a new DRAFT taxonomy version (ratification stays a
    # separate, human-only step); Calibration Agent only ever logs flags
    # for a human to act on.
    taxonomy_researcher_state_dir: Path = Field(default=REPO_ROOT / "backend" / ".taxonomy_researcher_state")
    taxonomy_researcher_schedule_enabled: bool = Field(default=False)
    taxonomy_researcher_schedule_interval_hours: float = Field(default=168.0, description="Weekly by default -- taxonomies don't need daily rescanning.")
    taxonomy_researcher_min_authority_score: float = Field(
        default=0.6, description="Minimum LLM-assessed authority_score for a discovered source to feed a proposal."
    )
    taxonomy_researcher_max_sources: int = Field(
        default=3, description="Top-N ranked authority-source candidates used per taxonomy scanned."
    )

    calibration_agent_state_dir: Path = Field(default=REPO_ROOT / "backend" / ".calibration_state")
    calibration_agent_schedule_enabled: bool = Field(default=False)
    calibration_agent_schedule_interval_hours: float = Field(default=24.0)

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

    # Continuous monitoring & alerting (arp/portfolio/monitoring/). Clones
    # discovery/scheduler.py's AsyncIOScheduler + JSON-persisted-config
    # pattern -- see CalibrationAgentScheduler for the closer analog: this
    # agent also only ever raises alerts for a human to act on, never
    # auto-resolves anything.
    portfolio_monitoring_state_dir: Path = Field(default=REPO_ROOT / "backend" / ".portfolio_monitoring_state")
    portfolio_monitoring_schedule_enabled: bool = Field(default=False)
    portfolio_monitoring_schedule_interval_hours: float = Field(default=6.0)
    portfolio_monitoring_news_min_severity: str = Field(
        default="medium", description="Minimum NewsRiskFlag.severity that opens a news_controversy alert."
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

    # Optional OpenSearch store (arp/storage/opensearch_client.py, requires
    # the `opensearch` extra: pip install -e ".[opensearch]"). Additive:
    # powers a new user-facing search feature (arp/api/routers/search.py)
    # and, opt-in, an alternate BM25 backend for select_relevant_chunks.
    # Never authoritative for anything -- OpenSearch holds retrieval-only
    # evidence/embeddings, never approved facts (see company_facts_* below).
    opensearch_url: str | None = Field(
        default=None,
        description="OpenSearch endpoint, e.g. http://localhost:9200. None (default) disables the user-facing "
        "search feature and the 'opensearch' retrieval_backend option; BM25/hybrid retrieval and every other "
        "feature are unaffected.",
    )
    search_live_indexing_enabled: bool = Field(
        default=False,
        description="When true (and opensearch_url is set), index each newly registered document into OpenSearch "
        "at ingestion time (arp/ingestion/local_files.py, edgar.py), best-effort -- an indexing failure is logged, "
        "never fails ingestion. Off by default so opting into OpenSearch never changes ingestion behavior; run "
        "'arp db reindex opensearch' for a one-time backfill regardless of this flag.",
    )
    retrieval_backend: str = Field(
        default="bm25",
        description="'bm25' (default, in-memory LlamaIndex BM25Retriever, see arp/retrieval/index_cache.py) or "
        "'opensearch' (requires opensearch_url) for select_relevant_chunks' keyword-ranking component. Either way "
        "the hybrid_retrieval_enabled local-embedding fusion is unaffected -- this only changes who computes the "
        "BM25 half.",
    )

    # Optional S3-compatible object store (arp/storage/object_store_client.py,
    # requires the `object_storage` extra: pip install -e ".[object_storage]").
    # Additive: holds an immutable copy of each source document's original
    # bytes (MinIO locally, any S3-compatible endpoint in production),
    # keyed by the same content hash DocumentContentStore already computes.
    # Never a replacement for the parsed-text cache or for any queryable/
    # searchable store -- it exists purely so an original source file is
    # always retrievable even if the local working copy is gone.
    object_store_endpoint_url: str | None = Field(
        default=None,
        description="S3-compatible endpoint, e.g. http://localhost:9000 (MinIO). None (default) disables object "
        "storage entirely -- documents stay only in the local documents_dir, exactly as today.",
    )
    object_store_access_key: str | None = Field(default=None, description="Access key for object_store_endpoint_url.")
    object_store_secret_key: str | None = Field(default=None, description="Secret key for object_store_endpoint_url.")
    object_store_bucket: str = Field(default="arp-documents", description="Bucket for immutable source-document copies.")
    object_store_live_upload_enabled: bool = Field(
        default=False,
        description="When true (and object_store_endpoint_url is set), upload each newly registered document's raw "
        "original bytes to object storage at ingestion time, best-effort -- an upload failure is logged, never "
        "fails ingestion. Off by default; run 'arp db reindex object-store' for a one-time backfill regardless.",
    )

    # Postgres read-model projections beyond Portfolio/Holdings (see
    # postgres_models.py's module docstring for the original narrower
    # scope). Each mirrors an existing file/SQLite store -- which stays
    # authoritative and unmodified either way -- into a queryable Postgres
    # table. All require postgres_dsn; all default off.
    document_registry_projection_enabled: bool = Field(
        default=False,
        description="Mirrors DocumentRegistry (SQLite, always authoritative) into Postgres as a queryable "
        "read-model (requires postgres_dsn) for relational joins against OpenSearch's doc_id hits. Additive only "
        "-- SQLite stays the source of truth either way; see arp/storage/postgres_document_projection.py.",
    )
    company_records_projection_enabled: bool = Field(
        default=False,
        description="Mirrors each completed run's results (extraction, financials, theme matches, voting ballots "
        "-- anything produced via RunStore/results.jsonl) into a queryable Postgres history table (requires "
        "postgres_dsn), on run completion. Additive only -- results.jsonl is never written to by this; see "
        "arp/storage/postgres_company_records_projection.py.",
    )
    company_facts_projection_enabled: bool = Field(
        default=False,
        description="Materializes each run's results plus the review_queue's decisions into a queryable, "
        "insert-only/versioned 'current approved value per company+field' table (requires postgres_dsn) -- the "
        "generalization of PortfolioStore.latest_observation to every pipeline. Additive only -- "
        "review_decisions.jsonl is never written to by this; see arp/storage/postgres_company_facts_projection.py.",
    )
    engagement_projection_enabled: bool = Field(
        default=False,
        description="Mirrors EngagementStore's current per-company issue/commitment state (record.json, always "
        "authoritative) into queryable Postgres tables (requires postgres_dsn), on every save. Additive only -- "
        "record.json/events.jsonl are never written to by this; see arp/storage/postgres_engagement_projection.py.",
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
            self.reports_dir,
            self.report_templates_dir,
            self.emerging_themes_state_dir,
            self.taxonomy_researcher_state_dir,
            self.calibration_agent_state_dir,
            self.portfolio_monitoring_state_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
