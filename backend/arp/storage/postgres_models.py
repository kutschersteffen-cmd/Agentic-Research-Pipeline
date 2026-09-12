"""SQLAlchemy ORM models for the opt-in Postgres/pgvector store (see
arp/storage/postgres.py, arp/storage/postgres_portfolio_store.py,
arp/storage/postgres_embeddings.py). Imported lazily by those modules only
-- never imported by the rest of this codebase, so a deployment that never
sets ARP_POSTGRES_DSN never needs sqlalchemy/psycopg/pgvector installed.

Two shapes of model live here, matching two different roles:

- **Dual-write, relational-join-driven** (Portfolio/Securities/Companies/
  Holdings, the hybrid-retrieval embeddings cache): the original,
  narrowest scope -- a relational/vector engine earns its cost purely for
  the join/lookup pattern (aggregating holdings by sector/issuer/
  portfolio across time; per-chunk embedding lookup).
- **Projection-only read models** (DocumentRegistryModel,
  CompanyRecordModel, CompanyFactModel): mirror an authoritative file/
  SQLite store into a queryable table via a best-effort sync hook (see
  arp/storage/postgres_company_records_projection.py,
  postgres_company_facts_projection.py, postgres_document_projection.py)
  -- never written to directly, never a second source of truth. The
  file/SQLite store they mirror stays authoritative and fully functional
  whether or not this projection is enabled.

Every run/review-queue/audit-trail store's *write path* stays file-based
JSONL regardless of which models above exist -- an append-only file is
simpler to keep fully auditable than a table with UPDATEs. See
docs/METHODOLOGY.md for the full reasoning, and each model's own
docstring for what it specifically projects and why.
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from arp.retrieval.embeddings import EMBED_DIM


class Base(DeclarativeBase):
    pass


class PortfolioModel(Base):
    __tablename__ = "portfolios"

    portfolio_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)


class CompanyModel(Base):
    __tablename__ = "companies"

    company_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    website: Mapped[str | None] = mapped_column(String, nullable=True)
    cik: Mapped[str | None] = mapped_column(String, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    isic_code: Mapped[str | None] = mapped_column(String, nullable=True)


class SecurityModel(Base):
    __tablename__ = "securities"

    security_id: Mapped[str] = mapped_column(String, primary_key=True)
    isin: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String)
    asset_class: Mapped[str] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.company_id"), nullable=True)


class SecurityResolutionModel(Base):
    """No FK to `securities`/`companies` deliberately: entity resolution
    (arp/portfolio/entity_resolution.py) can run against a custodian
    feed's SecurityRef before or independently of that security ever
    being persisted via save_security, matching the file-based
    PortfolioStore's equivalent lack of referential-integrity enforcement
    -- an FK here would reject a legitimate resolution result."""

    __tablename__ = "security_resolutions"

    security_id: Mapped[str] = mapped_column(String, primary_key=True)
    company_id: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String)
    needs_review: Mapped[bool] = mapped_column(default=False)
    resolved_at: Mapped[str] = mapped_column(String)


class HoldingModel(Base):
    """One position: one security, in one portfolio, as of one date.
    Immutable once written, matching arp/schemas/portfolio.py::Holding's
    own contract -- a correction is a new snapshot (new as_of_date or a
    superseding row), never an UPDATE of an existing one."""

    __tablename__ = "holdings"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "security_id", "as_of_date", name="uq_holdings_portfolio_security_date"),
        Index("ix_holdings_as_of_date_portfolio", "as_of_date", "portfolio_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.portfolio_id"))
    security_id: Mapped[str] = mapped_column(ForeignKey("securities.security_id"))
    as_of_date: Mapped[str] = mapped_column(String)
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    market_value: Mapped[float] = mapped_column(Float)
    fx_rate_to_eur: Mapped[float] = mapped_column(Float, default=1.0)
    market_value_eur: Mapped[float] = mapped_column(Float)
    weight_pct: Mapped[float | None] = mapped_column(Float, nullable=True)


class ChunkEmbeddingModel(Base):
    """pgvector-backed alternative to DocumentContentStore's SQLite
    embeddings cache (arp/storage/document_store.py) -- same
    chunk_id+embed_model key, same "computed once, reused by every later
    run/field/activity that selects from this chunk" role, just persisted
    in Postgres instead of a local SQLite file (e.g. for a shared cache
    across multiple worker processes/machines). EMBED_DIM is fixed at the
    currently configured embedding model's dimension (see
    arp/retrieval/embeddings.py) -- switching to a different-dimension
    model requires dropping and recreating this table.
    """

    __tablename__ = "chunk_embeddings"

    chunk_id: Mapped[str] = mapped_column(String, primary_key=True)
    embed_model: Mapped[str] = mapped_column(String, primary_key=True)
    embedding = mapped_column(Vector(EMBED_DIM))


class DocumentRegistryModel(Base):
    """Read-model projection of DocumentRegistry (SQLite, always
    authoritative -- see arp/storage/document_registry.py). Additive
    only: lets OpenSearch's doc_id-only hits (arp/storage/
    opensearch_indices.py) join back to relational company/doc_type
    facts in one query, and enables cross-company dedup queries that
    today require scanning SQLite row-by-row. Selected via
    Settings.document_registry_projection_enabled; SQLite is unaffected
    either way."""

    __tablename__ = "document_registry"
    __table_args__ = (Index("ix_document_registry_company_type", "company_id", "doc_type"),)

    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    company_id: Mapped[str] = mapped_column(String)
    doc_type: Mapped[str] = mapped_column(String)
    content_key: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    local_path: Mapped[str | None] = mapped_column(String, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    first_seen_at: Mapped[str] = mapped_column(String)
    last_seen_at: Mapped[str] = mapped_column(String)


class CompanyRecordModel(Base):
    """Read-model projection of every completed run's results.jsonl rows
    (results.jsonl stays authoritative -- see arp/storage/run_store.py).
    Covers every run type uniformly (extraction, financials, theme
    matches, voting ballots all flow through the same RunStore/
    results.jsonl/JobManager machinery) -- the analog of
    PostgresPortfolioStore.aggregate_market_value_eur for "everything a
    run produces about a company": today, answering "every needs_review
    extraction for company X" or "this company's full theme-match
    history" requires loading a different run type's results.jsonl into
    Python by hand.

    `record_key` is NOT NULL with a "" default rather than nullable:
    every verified run type (extraction/financials/theme/voting) writes
    exactly one results.jsonl row per company per run (`row["_key"]`,
    see arp/orchestration/batch_runner.py's _KEY_FIELD), so there is no
    natural finer key at this table's granularity today -- but Postgres
    treats NULL as distinct from NULL in a UNIQUE constraint, so a
    nullable record_key would silently defeat uq_company_records_run_
    company_key's whole idempotency purpose. "" is reserved for exactly
    that "no finer key" case; a future run type with genuinely multiple
    reviewable rows per company per run would populate a real value here.

    `payload` (JSONB, GIN-indexable) keeps the full row verbatim,
    queryable without a migration every time a new run type or
    extraction schema is added -- only the columns actually filtered/
    sorted/aggregated across runs get their own typed column.
    """

    __tablename__ = "company_records"
    __table_args__ = (
        UniqueConstraint("run_id", "company_id", "record_key", name="uq_company_records_run_company_key"),
        Index("ix_company_records_company_type", "company_id", "run_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String)
    run_type: Mapped[str] = mapped_column(String)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"))
    record_key: Mapped[str] = mapped_column(String, default="")
    overall_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    needs_review: Mapped[bool | None] = mapped_column(nullable=True)
    generated_at: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSONB)


class CompanyFactModel(Base):
    """The current-state layer: "what do we currently believe about
    company X's field Y, and who approved it" -- separate from
    CompanyRecordModel's raw per-run history above. Generalizes
    PortfolioStore.latest_observation's role (today scoped to Portfolio
    Monitoring only) across every pipeline that produces reviewable
    facts, materialized from each run's results plus
    orchestration/review_queue.py's decisions (review_decisions.jsonl
    stays authoritative; this table is never written to except by the
    projection sync).

    Insert-only and versioned, not upserted in place: a correction never
    overwrites a row -- it closes the current one (`valid_to`,
    `is_current=False`, `superseded_by_id`) and inserts a new one -- so
    "what did we believe about field Y for company X as of date Z" is a
    direct, indexed query, not a JSONL-history reconstruction.

    `status` is one of: "approved" | "edited" | "rejected" (a decision
    was recorded in review_queue.py), "pending_review" (the item was
    queued for review but no decision has been recorded yet -- a fact
    row still gets materialized so a caller can see a draft is pending
    review, but should treat its value as provisional), or
    "auto_approved" (never queued for review at all, i.e. implicitly
    trusted, matching this system's existing behavior).
    """

    __tablename__ = "company_facts"
    __table_args__ = (
        Index("ix_company_facts_current", "company_id", "fact_key", "as_of", "is_current"),
        Index("ix_company_facts_type", "company_id", "fact_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"))
    fact_key: Mapped[str] = mapped_column(String)
    as_of: Mapped[str] = mapped_column(String, default="")
    fact_type: Mapped[str] = mapped_column(String)
    value: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    citations: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_run_id: Mapped[str] = mapped_column(String)
    reviewer: Mapped[str | None] = mapped_column(String, nullable=True)
    valid_from: Mapped[str] = mapped_column(String)
    valid_to: Mapped[str | None] = mapped_column(String, nullable=True)
    is_current: Mapped[bool] = mapped_column(default=True)
    superseded_by_id: Mapped[int | None] = mapped_column(ForeignKey("company_facts.id"), nullable=True)


class IndexCheckpointModel(Base):
    """Per-projector high-water mark (e.g. "documents", "company_records",
    "company_facts") so `arp db reindex ...` without --full only rescans
    what's new since the last backfill/sync, instead of a full rescan
    every time."""

    __tablename__ = "index_checkpoints"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    last_synced_at: Mapped[str] = mapped_column(String)
