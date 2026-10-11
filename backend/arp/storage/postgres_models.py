"""SQLAlchemy ORM models for the Postgres tables outside the company foundation (that one is
arp/db/models.py, on the same `Base`): portfolios, securities, holdings and security resolutions
(arp/storage/postgres_portfolio_store.py), chunk embeddings (pgvector), engagement mirrors,
published facts/releases/events (arp/publish/facts.py) and the BI-published rows.

`legacy_companies` is the portfolio store's company table, keyed by universe id; it is not the
registry (`companies`). Tables that predate the registry keep their legacy keys (issuer_key/
issuer_scheme, universe id) and carry the registry company in `company_id` (`company_uuid` where
`company_id` already holds the universe id), set by the live writers and backfilled by schema step
`phase1_rekey` (arp/storage/postgres_schema.py).

Tables earlier versions wrote and no model defines any more (`company_records`,
`legacy_company_facts`, `document_registry`, `index_checkpoints`) are never dropped by this code:
`arp db import` reads `document_registry`. docs/INSTALLATION.md gives the manual DROP once
`arp db verify` is clean.
"""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from arp.retrieval.embeddings import EMBED_DIM


class Base(DeclarativeBase):
    pass


def _company_ref(table: str, column: str = "company_id") -> Mapped[uuid.UUID | None]:
    """The registry company (`companies.id`) a legacy-keyed row belongs to. NULL until step
    `phase1_rekey` (or `arp db import`) matches it; the FK is named so that step can add it to an
    existing table."""
    return mapped_column(Uuid, ForeignKey("companies.id", name=f"fk_{table}_{column}"), nullable=True)


class PortfolioModel(Base):
    __tablename__ = "portfolios"

    portfolio_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)


class CompanyModel(Base):
    __tablename__ = "legacy_companies"

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
    company_id: Mapped[str | None] = mapped_column(ForeignKey("legacy_companies.company_id"), nullable=True)
    # `company_id` above is the universe id (legacy_companies); this is the registry company.
    company_uuid: Mapped[uuid.UUID | None] = _company_ref("securities", "company_uuid")


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
    company_uuid: Mapped[uuid.UUID | None] = _company_ref("security_resolutions", "company_uuid")


class HoldingModel(Base):
    """One position: one security, held by one index or portfolio
    (`kind`; `portfolio_id` holds the holder id), as of one date.
    Immutable once written, matching arp/schemas/portfolio.py::Holding's
    own contract -- a correction is a new snapshot (new as_of_date or a
    superseding row), never an UPDATE of an existing one."""

    __tablename__ = "holdings"
    __table_args__ = (
        UniqueConstraint("kind", "portfolio_id", "security_id", "as_of_date", name="uq_holdings_kind_holder_security_date"),
        Index("ix_holdings_as_of_date_portfolio", "as_of_date", "portfolio_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String, default="portfolio", server_default="portfolio")
    # Holds Holding.holder_id (an index or a portfolio), so no FK to portfolios.
    portfolio_id: Mapped[str] = mapped_column(String)
    security_id: Mapped[str] = mapped_column(ForeignKey("securities.security_id"))
    as_of_date: Mapped[str] = mapped_column(String)
    isin: Mapped[str | None] = mapped_column(String, nullable=True)
    issuer_key: Mapped[str | None] = mapped_column(String, nullable=True)
    issuer_scheme: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    currency: Mapped[str | None] = mapped_column(String, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    fx_rate_to_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_value_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    shares: Mapped[float | None] = mapped_column(Float, nullable=True)
    free_float: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    company_id: Mapped[uuid.UUID | None] = _company_ref("holdings")


class ChunkEmbeddingModel(Base):
    """The chunk-embeddings cache (pgvector; arp/storage/postgres_embeddings.py, used by
    DocumentContentStore): keyed by chunk_id + embed_model, computed once and reused by every later
    run/field/activity that selects from this chunk. EMBED_DIM is fixed at the configured embedding
    model's dimension (arp/retrieval/embeddings.py) -- switching to a different-dimension model
    requires dropping and recreating this table.
    """

    __tablename__ = "chunk_embeddings"

    chunk_id: Mapped[str] = mapped_column(String, primary_key=True)
    embed_model: Mapped[str] = mapped_column(String, primary_key=True)
    embedding = mapped_column(Vector(EMBED_DIM))


class EngagementIssueModel(Base):
    """Read-model projection of one EngagementIssue inside a company's
    EngagementRecord (arp/storage/engagement_store.py, `record.json` --
    always authoritative; `events.jsonl` remains the separate, untouched
    audit trail). Engagement state is a continuously-mutated live document, not a run
    output, so this table is a full replace-by-company_id snapshot on
    every EngagementStore._save -- not an append-only history.

    Makes "every open/stalled high-severity issue across the portfolio"
    a single indexed query instead of scanning every company's
    record.json. Correspondence entries and milestone/escalation history
    stay inside `payload` (JSONB) -- they're an append-only trail read as
    a whole for one issue, not filtered independently across companies,
    so a dedicated table would add join cost with no query it actually
    serves.

    `company_id` is the universe id, a plain String with no FK. (`EngagementCommitmentModel.issue_id` below does
    keep its FK: sync_record writes both rows in one transaction, so that
    one can always be satisfied.)
    """

    __tablename__ = "engagement_issues"
    __table_args__ = (Index("ix_engagement_issues_company_status", "company_id", "status"),)

    issue_id: Mapped[str] = mapped_column(String, primary_key=True)
    company_id: Mapped[str] = mapped_column(String)
    theme: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    milestone_stage: Mapped[str] = mapped_column(String)
    escalation_stage: Mapped[str] = mapped_column(String)
    opened_at: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSONB)


class EngagementCommitmentModel(Base):
    """Read-model projection of one Commitment nested inside an
    EngagementIssue -- broken out into its own table (rather than left
    inside EngagementIssueModel.payload) because "every overdue
    commitment across the portfolio" is a real cross-company query this
    table serves directly, unlike correspondence/milestone/escalation
    history."""

    __tablename__ = "engagement_commitments"
    __table_args__ = (Index("ix_engagement_commitments_company_status", "company_id", "status"),)

    commitment_id: Mapped[str] = mapped_column(String, primary_key=True)
    issue_id: Mapped[str] = mapped_column(ForeignKey("engagement_issues.issue_id"))
    company_id: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    target_date: Mapped[str | None] = mapped_column(String, nullable=True)
    validated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    validated_at: Mapped[str | None] = mapped_column(String, nullable=True)


class ReleaseModel(Base):
    """One publication of a source document for an issuer in a run (E17).
    `published_by` / `withdrawn_by` are internal user ids and never served."""

    __tablename__ = "releases"
    __table_args__ = (Index("ix_releases_doc", "doc_id"), Index("ix_releases_run", "run_id"))

    release_id: Mapped[str] = mapped_column(String, primary_key=True)
    doc_id: Mapped[str] = mapped_column(String)
    content_key: Mapped[str] = mapped_column(String)
    storage_uri: Mapped[str] = mapped_column(String)
    issuer_key: Mapped[str] = mapped_column(String)
    issuer_scheme: Mapped[str] = mapped_column(String)
    run_id: Mapped[str] = mapped_column(String)
    published_at: Mapped[str] = mapped_column(String)
    published_by: Mapped[str] = mapped_column(String)
    published_by_role: Mapped[str] = mapped_column(String)
    withdrawn_at: Mapped[str | None] = mapped_column(String, nullable=True)
    withdrawal_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    withdrawn_by: Mapped[str | None] = mapped_column(String, nullable=True)
    company_id: Mapped[uuid.UUID | None] = _company_ref("releases")


class PublishedFactModel(Base):
    """Insert-only versioned published fact (E72): a change closes the
    current row (`valid_to`, `superseded_by`) and inserts the next version."""

    __tablename__ = "published_facts"
    __table_args__ = (
        UniqueConstraint(
            "issuer_key", "field_id", "period_end", "basis", "version", name="uq_published_facts_key_version"
        ),
        Index("ix_published_facts_current", "issuer_key", "field_id", "period_end", "basis", "valid_to"),
        Index("ix_published_facts_valid_from", "valid_from"),
        # Not unique: rows of one company published under two issuer keys (LEI before cut-over, the
        # registry UUID after) share a version number, so the natural key stays the issuer_key one above.
        Index("ix_published_facts_company_key", "company_id", "field_id", "period_end", "basis"),
    )

    fact_id: Mapped[str] = mapped_column(String, primary_key=True)
    issuer_key: Mapped[str] = mapped_column(String)
    issuer_scheme: Mapped[str] = mapped_column(String)
    field_id: Mapped[str] = mapped_column(String)
    period_end: Mapped[str] = mapped_column(String)
    basis: Mapped[str] = mapped_column(String, default="")
    value: Mapped[object] = mapped_column(JSONB)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    canonical_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    canonical_unit: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(String)
    citation: Mapped[dict] = mapped_column(JSONB)
    source_run_id: Mapped[str] = mapped_column(String)
    observed_at: Mapped[str] = mapped_column(String)
    item_key: Mapped[str] = mapped_column(String)
    restated: Mapped[bool] = mapped_column(default=False)
    restated_by_doc_id: Mapped[str | None] = mapped_column(String, nullable=True)
    version: Mapped[int] = mapped_column()
    valid_from: Mapped[str] = mapped_column(String)
    valid_to: Mapped[str | None] = mapped_column(String, nullable=True)
    superseded_by: Mapped[str | None] = mapped_column(ForeignKey("published_facts.fact_id"), nullable=True)
    reconfirmed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    release_id: Mapped[str] = mapped_column(ForeignKey("releases.release_id"))
    restored_from: Mapped[str | None] = mapped_column(String, nullable=True)
    company_id: Mapped[uuid.UUID | None] = _company_ref("published_facts")


class FactEventModel(Base):
    """Outbox of fact changes, ordered by the autoincrement `event_id`."""

    __tablename__ = "fact_events"
    __table_args__ = (Index("ix_fact_events_at", "at"),)

    event_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String)
    fact_id: Mapped[str] = mapped_column(String)
    issuer_key: Mapped[str] = mapped_column(String)
    field_id: Mapped[str] = mapped_column(String)
    period_end: Mapped[str] = mapped_column(String)
    basis: Mapped[str] = mapped_column(String)
    release_id: Mapped[str] = mapped_column(String)
    at: Mapped[str] = mapped_column(String)
    company_id: Mapped[uuid.UUID | None] = _company_ref("fact_events")


class BiPublishedModel(Base):
    """Rows the monthly run publishes for Superset, one JSON object per row (arp/bi/published.py).
    The `bi` views (arp/bi/views.py) cast them to typed columns. Derived data: no file store behind it."""

    __tablename__ = "bi_published"
    __table_args__ = (Index("ix_bi_published_dataset_month", "dataset", "month"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dataset: Mapped[str] = mapped_column(String)
    month: Mapped[str] = mapped_column(String)
    row: Mapped[dict] = mapped_column(JSONB)
