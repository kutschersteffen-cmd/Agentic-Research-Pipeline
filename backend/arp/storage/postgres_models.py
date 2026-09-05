"""SQLAlchemy ORM models for the opt-in Postgres/pgvector store (see
arp/storage/postgres.py, arp/storage/postgres_portfolio_store.py,
arp/storage/postgres_embeddings.py). Imported lazily by those modules only
-- never imported by the rest of this codebase, so a deployment that never
sets ARP_POSTGRES_DSN never needs sqlalchemy/psycopg/pgvector installed.

Scope is deliberate, not an oversight: only Portfolios/Securities/
Companies/Holdings (real relational-join load: aggregating holdings by
sector/issuer/portfolio across time) and the hybrid-retrieval embeddings
cache get a Postgres backend. Every run/review-queue/audit-trail store
elsewhere in this codebase stays file-based JSONL -- an append-only file
is simpler to keep fully auditable than a table with UPDATEs, and none of
those stores have the multi-way join access pattern that justifies a
relational engine's cost. See docs/METHODOLOGY.md for the full reasoning.
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
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
