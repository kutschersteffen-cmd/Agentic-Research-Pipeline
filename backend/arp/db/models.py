"""Company-foundation tables (spec §2): UUID companies, identifiers, fields, runs, documents,
sources, observations, review and current facts. Same `Base` as the legacy store so
`ensure_schema` creates them; nothing writes to them yet."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from arp.storage.postgres_models import Base


class IdScheme(StrEnum):
    """Built-in schemes. `company_identifiers.scheme` is a CHECKed string, so provider schemes need no migration."""

    LEI = "LEI"
    ISIN = "ISIN"
    CIK = "CIK"
    TICKER = "TICKER"
    UNIVERSE = "UNIVERSE"
    INTERNAL = "INTERNAL"
    MERGED_INTO = "MERGED_INTO"


class FieldKind(StrEnum):
    EXTRACTED = "extracted"
    PROVIDER = "provider"


class SourceKind(StrEnum):
    EXTRACTION = "extraction"
    PROVIDER = "provider"
    XBRL = "xbrl"
    MANUAL = "manual"


class ValueState(StrEnum):
    FOUND = "found"
    ZERO = "zero"
    NOT_FOUND = "not_found"
    NOT_APPLICABLE = "not_applicable"


class Route(StrEnum):
    AUTO_ACCEPT = "auto_accept"
    REVIEW = "review"
    HOLD = "hold"


class CitationRole(StrEnum):
    PRIMARY = "primary"
    CORROBORATING = "corroborating"
    ALTERNATIVE = "alternative"


class ItemState(StrEnum):
    PENDING = "pending"
    FIRST_DONE = "first_done"
    SECOND_DONE = "second_done"
    DISAGREED = "disagreed"
    FINAL = "final"


class DecisionKind(StrEnum):
    APPROVE = "approve"
    EDIT = "edit"
    CORRECT = "correct"
    REJECT = "reject"
    ESCALATE = "escalate"
    HOLD = "hold"


class FactStatus(StrEnum):
    AUTO_ACCEPTED = "auto_accepted"
    APPROVED = "approved"
    EDITED = "edited"
    PENDING_REVIEW = "pending_review"
    HELD = "held"


class SourceKindDS(StrEnum):
    API = "api"
    FILE = "file"


class Licence(StrEnum):
    INTERNAL_ONLY = "internal_only"
    REDISTRIBUTABLE = "redistributable"


class LoadStatus(StrEnum):
    FETCHED = "fetched"
    INGESTED = "ingested"
    FAILED = "failed"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _enum(cls: type[StrEnum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


_NOW = func.now()


def _id() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(), primary_key=True)


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=_NOW)


def _company_fk(nullable: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, ForeignKey("companies.id"), nullable=nullable)


# --- 2.1 companies ---------------------------------------------------------


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint(
            "fiscal_year_end ~ '^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$'", name="ck_companies_fiscal_year_end"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    sector: Mapped[str | None] = mapped_column(Text)
    isic_code: Mapped[str | None] = mapped_column(Text)
    fiscal_year_end: Mapped[str | None] = mapped_column(String(5))
    regimes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=text("'{}'"))
    created_at: Mapped[datetime] = _ts()


class CompanyIdentifier(Base):
    __tablename__ = "company_identifiers"
    __table_args__ = (
        CheckConstraint("scheme ~ '^[A-Z][A-Z0-9_]*$'", name="ck_company_identifiers_scheme"),
        Index("uq_company_identifiers_active", "scheme", "value", unique=True, postgresql_where=text("valid_to IS NULL")),
        Index("ix_company_identifiers_company", "company_id"),
    )

    id: Mapped[int] = _id()
    company_id: Mapped[uuid.UUID] = _company_fk()
    scheme: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(Text)
    valid_from: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    valid_to: Mapped[date | None] = mapped_column(Date)


# --- 2.4 sources (declared early: fields and documents point at them) -------


class DataSource(Base):
    __tablename__ = "data_sources"

    source_id: Mapped[int] = _id()
    slug: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[SourceKindDS] = mapped_column(_enum(SourceKindDS, "data_source_kind"))
    licence: Mapped[Licence] = mapped_column(_enum(Licence, "licence"))
    id_scheme: Mapped[str | None] = mapped_column(Text)


class SourceLoad(Base):
    __tablename__ = "source_loads"
    __table_args__ = (UniqueConstraint("source_id", "payload_sha", name="uq_source_loads_payload"),)

    load_id: Mapped[int] = _id()
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.source_id"))
    fetched_at: Mapped[datetime] = _ts()
    as_of: Mapped[date | None] = mapped_column(Date)
    request: Mapped[dict | None] = mapped_column(JSONB)
    payload_uri: Mapped[str | None] = mapped_column(Text)
    payload_sha: Mapped[str] = mapped_column(Text)
    status: Mapped[LoadStatus] = mapped_column(_enum(LoadStatus, "load_status"))


# --- 2.2 fields --------------------------------------------------------------
# The field_id CHECK is added by the `fields_id_check` schema step.


class Field(Base):
    __tablename__ = "fields"

    field_id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[FieldKind] = mapped_column(_enum(FieldKind, "field_kind"))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.source_id"))
    created_at: Mapped[datetime] = _ts()
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FieldDefinition(Base):
    __tablename__ = "field_definitions"

    field_id: Mapped[str] = mapped_column(ForeignKey("fields.field_id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    data_type: Mapped[str] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text)
    definition: Mapped[dict] = mapped_column(JSONB)
    effective_from: Mapped[date] = mapped_column(Date, server_default=func.current_date())


class DataSchema(Base):
    __tablename__ = "data_schemas"

    schema_id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by: Mapped[str | None] = mapped_column(Text)


class DataSchemaField(Base):
    __tablename__ = "data_schema_fields"
    __table_args__ = (
        ForeignKeyConstraint(["schema_id", "schema_version"], ["data_schemas.schema_id", "data_schemas.version"]),
        ForeignKeyConstraint(["field_id", "field_version"], ["field_definitions.field_id", "field_definitions.version"]),
        UniqueConstraint("schema_id", "schema_version", "field_id", name="uq_data_schema_fields"),
    )

    id: Mapped[int] = _id()
    schema_id: Mapped[str] = mapped_column(Text)
    schema_version: Mapped[int] = mapped_column(Integer)
    field_id: Mapped[str] = mapped_column(Text)
    field_version: Mapped[int] = mapped_column(Integer)


class ProviderMetricCode(Base):
    __tablename__ = "provider_metric_codes"
    __table_args__ = (UniqueConstraint("source_id", "provider_code", name="uq_provider_metric_codes"),)

    id: Mapped[int] = _id()
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.source_id"))
    provider_code: Mapped[str] = mapped_column(Text)
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.field_id"))


# --- 2.4 documents -------------------------------------------------------------


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_company_type", "company_id", "doc_type"),)

    doc_id: Mapped[str] = mapped_column(Text, primary_key=True)
    company_id: Mapped[uuid.UUID] = _company_fk()
    doc_type: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    content_key: Mapped[str] = mapped_column(Text)
    storage_uri: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    local_path: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[date | None] = mapped_column(Date)
    family_id: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int | None] = mapped_column(Integer)
    supersedes: Mapped[str | None] = mapped_column(ForeignKey("documents.doc_id"))
    first_seen_at: Mapped[datetime] = _ts()
    last_seen_at: Mapped[datetime] = _ts()
    identity_confidence: Mapped[float | None] = mapped_column(Float)
    identity_review: Mapped[bool | None] = mapped_column(Boolean)


# --- 2.3 runs --------------------------------------------------------------------


class Run(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_type: Mapped[str] = mapped_column(Text)
    status: Mapped[RunStatus] = mapped_column(_enum(RunStatus, "run_status"))
    params: Mapped[dict | None] = mapped_column(JSONB)
    company_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    completed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    review_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric)
    model: Mapped[str | None] = mapped_column(Text)
    verifier_model: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW, onupdate=_NOW)


class RunCompany(Base):
    __tablename__ = "run_companies"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id"), primary_key=True)


class RunResult(Base):
    __tablename__ = "run_results"
    __table_args__ = (UniqueConstraint("run_id", "company_id", name="uq_run_results"),)

    id: Mapped[int] = _id()
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"))
    company_id: Mapped[uuid.UUID] = _company_fk()
    result: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _ts()


class RunError(Base):
    __tablename__ = "run_errors"

    id: Mapped[int] = _id()
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"))
    company_id: Mapped[uuid.UUID | None] = _company_fk(nullable=True)
    error: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _ts()


class RunHeldDocument(Base):
    __tablename__ = "run_held_documents"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id"), primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.doc_id"), primary_key=True)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()


# --- 2.5 values --------------------------------------------------------------------


class FieldObservation(Base):
    """Insert-only."""

    __tablename__ = "field_observations"
    __table_args__ = (
        ForeignKeyConstraint(["field_id", "field_version"], ["field_definitions.field_id", "field_definitions.version"]),
        Index("ix_field_observations_key", "company_id", "field_id", "period_end"),
    )

    id: Mapped[int] = _id()
    company_id: Mapped[uuid.UUID] = _company_fk()
    field_id: Mapped[str] = mapped_column(Text)
    field_version: Mapped[int] = mapped_column(Integer)
    source_kind: Mapped[SourceKind] = mapped_column(_enum(SourceKind, "source_kind"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.run_id"))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.source_id"))
    load_id: Mapped[int | None] = mapped_column(ForeignKey("source_loads.load_id"))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    basis: Mapped[str] = mapped_column(Text, default="", server_default="")
    value: Mapped[dict | list | str | float | int | bool | None] = mapped_column(JSONB)
    value_state: Mapped[ValueState] = mapped_column(_enum(ValueState, "value_state"))
    unit: Mapped[str | None] = mapped_column(Text)
    canonical_value: Mapped[Decimal | None] = mapped_column(Numeric)
    canonical_unit: Mapped[str | None] = mapped_column(Text)
    scale_applied: Mapped[float | None] = mapped_column(Float)
    fx_rate: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    checks: Mapped[list | dict | None] = mapped_column(JSONB)
    route: Mapped[Route | None] = mapped_column(_enum(Route, "route"))
    method: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()


class ValueCitation(Base):
    __tablename__ = "value_citations"
    __table_args__ = (Index("ix_value_citations_observation", "observation_id"),)

    id: Mapped[int] = _id()
    observation_id: Mapped[int] = mapped_column(ForeignKey("field_observations.id"))
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.doc_id"))
    content_key: Mapped[str | None] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    sheet: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[str | None] = mapped_column(Text)
    span_text: Mapped[str | None] = mapped_column(Text)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    table_ref: Mapped[dict | None] = mapped_column(JSONB)
    passage_id: Mapped[str | None] = mapped_column(Text)
    grounded: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    match_method: Mapped[str | None] = mapped_column(Text)
    match_score: Mapped[float | None] = mapped_column(Float)
    role: Mapped[CitationRole] = mapped_column(_enum(CitationRole, "citation_role"), default=CitationRole.PRIMARY)


# --- 2.6 review --------------------------------------------------------------------


class ReviewItem(Base):
    __tablename__ = "review_items"
    __table_args__ = (UniqueConstraint("run_id", "item_key", name="uq_review_items_key"),)

    id: Mapped[int] = _id()
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"))
    company_id: Mapped[uuid.UUID] = _company_fk()
    item_key: Mapped[str | None] = mapped_column(Text)
    observation_id: Mapped[int | None] = mapped_column(ForeignKey("field_observations.id"))
    payload: Mapped[dict] = mapped_column(JSONB)
    state: Mapped[ItemState] = mapped_column(_enum(ItemState, "item_state"), default=ItemState.PENDING)
    queued_at: Mapped[datetime] = _ts()


class ReviewDecision(Base):
    """Insert-only."""

    __tablename__ = "review_decisions"

    id: Mapped[int] = _id()
    review_item_id: Mapped[int] = mapped_column(ForeignKey("review_items.id"))
    decision: Mapped[DecisionKind] = mapped_column(_enum(DecisionKind, "decision_kind"))
    reviewer: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    edited_value: Mapped[dict | list | str | float | int | bool | None] = mapped_column(JSONB)
    comment: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = _ts()


class ReviewCosign(Base):
    """Insert-only."""

    __tablename__ = "review_cosigns"

    id: Mapped[int] = _id()
    review_item_id: Mapped[int] = mapped_column(ForeignKey("review_items.id"))
    reviewer: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = _ts()


# --- 2.7 facts ----------------------------------------------------------------------


class CompanyFact(Base):
    """Current-fact layer; updated only to close a row (`valid_to`, `superseded_by`)."""

    __tablename__ = "company_facts"
    __table_args__ = (
        Index(
            "uq_company_facts_current",
            "company_id",
            "field_id",
            "period_end",
            "basis",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
    )

    id: Mapped[int] = _id()
    company_id: Mapped[uuid.UUID] = _company_fk()
    field_id: Mapped[str] = mapped_column(ForeignKey("fields.field_id"))
    period_end: Mapped[date | None] = mapped_column(Date)
    basis: Mapped[str] = mapped_column(Text, default="", server_default="")
    value: Mapped[dict | list | str | float | int | bool | None] = mapped_column(JSONB)
    canonical_value: Mapped[Decimal | None] = mapped_column(Numeric)
    canonical_unit: Mapped[str | None] = mapped_column(Text)
    status: Mapped[FactStatus] = mapped_column(_enum(FactStatus, "fact_status"))
    observation_id: Mapped[int] = mapped_column(ForeignKey("field_observations.id"))
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("review_decisions.id"))
    conflicting_sources: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    valid_from: Mapped[datetime] = _ts()
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by: Mapped[int | None] = mapped_column(ForeignKey("company_facts.id"))
