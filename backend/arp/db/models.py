"""Company-foundation tables (spec §2): UUID companies, identifiers, fields, runs, documents,
sources, observations, review and current facts. Same `Base` as the legacy store so
`ensure_schema` creates them. arp.db.runs.RunStore writes the run and review tables."""

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
    USER = "USER"  # a user's own id from an uploaded list (Argus step 1)


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
    error: Mapped[str | None] = mapped_column(Text)  # why the last ingest failed


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
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # set once a schema carrying it is released
    quality: Mapped[dict | None] = mapped_column(JSONB)  # FieldQuality (first audit), per field version


class DataSchema(Base):
    __tablename__ = "data_schemas"

    schema_id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by: Mapped[str | None] = mapped_column(Text)
    release_flag: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    body: Mapped[dict | None] = mapped_column(JSONB)  # full DataPointSchema dump; get() round-trips it


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
    __table_args__ = (
        Index("ix_documents_company_type", "company_id", "doc_type"),
        Index("ix_documents_content", "content_key"),
    )

    doc_id: Mapped[str] = mapped_column(Text, primary_key=True)
    company_id: Mapped[uuid.UUID] = _company_fk()
    universe_id: Mapped[str | None] = mapped_column(Text)  # display only: original-case universe id; filter by company_id
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


class TextItem(Base):
    """Insert-only point-in-time text: a correction is a new row with a later knowledge_time."""

    __tablename__ = "text_items"
    __table_args__ = (
        UniqueConstraint("source", "source_item_id", "content_hash", name="uq_text_items_version"),
        Index("ix_text_items_company_event", "company_id", "event_time"),
        Index("ix_text_items_item_knowledge", "source", "source_item_id", "knowledge_time"),
    )

    item_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    source_item_id: Mapped[str] = mapped_column(Text)
    company_id: Mapped[str | None] = mapped_column(Text)  # plain issuer key, no foreign key
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    knowledge_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revision_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)


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
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    cache_creation_tokens: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric)
    batch_saved_usd: Mapped[Decimal | None] = mapped_column(Numeric)
    batch_wait: Mapped[dict | None] = mapped_column(JSONB)  # the open Message Batch(es) the run waits on
    model: Mapped[str | None] = mapped_column(Text)
    verifier_model: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # Set by RunStore.save_companies, even when every ref was an identity conflict and none is stored.
    companies_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW, onupdate=_NOW)


class RunCompany(Base):
    __tablename__ = "run_companies"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    ref: Mapped[dict] = mapped_column(JSONB)  # CompanyRef dump as saved; load_companies returns it


class RunResult(Base):
    __tablename__ = "run_results"
    __table_args__ = (UniqueConstraint("run_id", "result_key", name="uq_run_results_key"),)

    id: Mapped[int] = _id()
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"))
    result_key: Mapped[str] = mapped_column(Text)  # row["_key"]; not every run type keys by company
    company_id: Mapped[uuid.UUID | None] = _company_fk(nullable=True)
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
    company_id: Mapped[uuid.UUID | None] = _company_fk(nullable=True)
    item_key: Mapped[str] = mapped_column(Text)
    observation_id: Mapped[int | None] = mapped_column(ForeignKey("field_observations.id"))
    payload: Mapped[dict] = mapped_column(JSONB)
    state: Mapped[ItemState] = mapped_column(_enum(ItemState, "item_state"), default=ItemState.PENDING)
    queued_at: Mapped[datetime] = _ts()


class ReviewItemObservation(Base):
    """The observations a review item decides: a value item's one observation, a whole-record item's
    every observation of its run and company routed to review. Written when the item is queued."""

    __tablename__ = "review_item_observations"

    review_item_id: Mapped[int] = mapped_column(ForeignKey("review_items.id"), primary_key=True)
    observation_id: Mapped[int] = mapped_column(ForeignKey("field_observations.id"), primary_key=True)


class ReviewDecision(Base):
    """Insert-only."""

    __tablename__ = "review_decisions"

    id: Mapped[int] = _id()
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"))
    # NULL when the item was never queued (auto-accepted values, emerging-theme candidate decisions)
    review_item_id: Mapped[int | None] = mapped_column(ForeignKey("review_items.id"))
    decision: Mapped[DecisionKind | None] = mapped_column(_enum(DecisionKind, "decision_kind"))  # NULL: not a DecisionKind
    row: Mapped[dict] = mapped_column(JSONB)  # the decision row as appended; read_decisions returns it
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
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"))
    review_item_id: Mapped[int | None] = mapped_column(ForeignKey("review_items.id"))
    row: Mapped[dict] = mapped_column(JSONB)  # the cosign row as appended
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
            postgresql_nulls_not_distinct=True,  # theme/vote facts have no period_end
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


# --- transition barrier: analyst facts (append-only) -----------------------------------


class BarrierDocument(Base):
    """An uploaded PDF used only to check one analyst fact's quote."""

    __tablename__ = "barrier_documents"

    id: Mapped[int] = _id()
    title: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(Text)
    as_of: Mapped[date] = mapped_column(Date)
    tier: Mapped[str] = mapped_column(Text)
    filename: Mapped[str | None] = mapped_column(Text)
    content_key: Mapped[str] = mapped_column(Text)  # sha256 of the bytes, the blob store key
    page_texts: Mapped[list] = mapped_column(JSONB)
    uploaded_by: Mapped[str] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = _ts()


class BarrierSourceDocument(Base):
    """A registered source fetched from its URL; a changed document adds a row."""

    __tablename__ = "barrier_source_documents"
    __table_args__ = (Index("ix_barrier_source_documents_key", "source_key", "id"),)

    id: Mapped[int] = _id()
    source_key: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)  # the source's source_name
    publisher: Mapped[str] = mapped_column(Text)
    tier: Mapped[str] = mapped_column(Text)
    as_of: Mapped[date] = mapped_column(Date)
    content_key: Mapped[str] = mapped_column(Text)  # sha256 of the bytes, the blob store key
    content_type: Mapped[str] = mapped_column(Text)
    page_texts: Mapped[list] = mapped_column(JSONB)
    html: Mapped[bool] = mapped_column(Boolean)
    fetched_at: Mapped[datetime] = _ts()


class BarrierExtraction(Base):
    """The model's answer for one fact in one stored source document, as given (source value and unit) with its
    quote grounding; the code checks run on it when it is read. A not-found answer is kept too (found False)."""

    __tablename__ = "barrier_extractions"
    __table_args__ = (
        UniqueConstraint("code", "region", "fact", "source_document_id", "fingerprint", name="uq_barrier_extractions_key"),
    )

    id: Mapped[int] = _id()
    code: Mapped[str] = mapped_column(Text)
    region: Mapped[str] = mapped_column(Text)
    fact: Mapped[str] = mapped_column(Text)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("barrier_source_documents.id"))
    fingerprint: Mapped[str] = mapped_column(Text)  # the fact definition and prompt version it was extracted with
    found: Mapped[bool] = mapped_column(Boolean)
    value: Mapped[str | float | bool | None] = mapped_column(JSONB)  # as the source states it
    unit: Mapped[str | None] = mapped_column(Text)  # the source's unit text
    quote: Mapped[str | None] = mapped_column(Text)  # "" when the model cited nothing
    grounded: Mapped[bool | None] = mapped_column(Boolean)  # the quote was found in a passage the model was shown
    page: Mapped[int | None] = mapped_column(Integer)
    locator: Mapped[str | None] = mapped_column(Text)
    as_of: Mapped[date | None] = mapped_column(Date)
    run_id: Mapped[str] = mapped_column(Text)
    extracted_at: Mapped[datetime] = _ts()


class BarrierFact(Base):
    __tablename__ = "barrier_facts"
    __table_args__ = (Index("ix_barrier_facts_cell", "code", "region"),)

    id: Mapped[int] = _id()
    code: Mapped[str] = mapped_column(Text)
    region: Mapped[str] = mapped_column(Text)
    fact: Mapped[str] = mapped_column(Text)
    value: Mapped[dict | list | str | float | int | bool | None] = mapped_column(JSONB)
    unit: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    locator: Mapped[str | None] = mapped_column(Text)
    source_key: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("barrier_documents.id"))
    entered_by: Mapped[str] = mapped_column(Text)
    entered_at: Mapped[datetime] = _ts()
    machine_checked: Mapped[bool] = mapped_column(Boolean)


class BarrierChoice(Base):
    __tablename__ = "barrier_choices"
    __table_args__ = (Index("ix_barrier_choices_cell", "code", "region"),)

    id: Mapped[int] = _id()
    code: Mapped[str] = mapped_column(Text)
    region: Mapped[str] = mapped_column(Text)
    fact: Mapped[str] = mapped_column(Text)  # the rule book fact id
    fact_id: Mapped[str] = mapped_column(Text)  # the chosen value's id (a barrier_facts id)
    reason: Mapped[str] = mapped_column(Text)
    value_ids: Mapped[list] = mapped_column(JSONB)  # every value id for the fact when the choice was made
    chosen_by: Mapped[str] = mapped_column(Text)
    chosen_at: Mapped[datetime] = _ts()


# --- RFP answers ------------------------------------------------------------------------


class RfpLibraryEntry(Base):
    """One approved question-and-answer pair. Its source: a file and location, a project, or `written_by`."""

    __tablename__ = "rfp_library_entries"

    id: Mapped[int] = _id()
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    source_file: Mapped[str | None] = mapped_column(Text)
    source_location: Mapped[str | None] = mapped_column(Text)
    source_project_id: Mapped[int | None] = mapped_column(BigInteger)
    written_by: Mapped[str | None] = mapped_column(Text)
    approved_on: Mapped[date] = mapped_column(Date)
    review_by: Mapped[date] = mapped_column(Date)
    owner: Mapped[str | None] = mapped_column(Text)
    has_figures: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")  # active | retired


class RfpProject(Base):
    """An incoming RFP: the investor's original file (blob store key) and its detect-and-fill run."""

    __tablename__ = "rfp_projects"

    id: Mapped[int] = _id()
    investor: Mapped[str] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    filename: Mapped[str] = mapped_column(Text)
    content_key: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(Text)
    run_status: Mapped[str] = mapped_column(Text)  # detecting | drafting | done | failed
    not_located: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()


class RfpQuestion(Base):
    __tablename__ = "rfp_questions"
    __table_args__ = (UniqueConstraint("project_id", "location", name="uq_rfp_questions_location"),)

    id: Mapped[int] = _id()
    project_id: Mapped[int] = mapped_column(ForeignKey("rfp_projects.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)  # file order
    location: Mapped[str] = mapped_column(Text)
    answer_location: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(Text)  # no source | drafted | edited | approved | left blank
    flags: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    sources: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))  # {entry_id, quote}
    assignee: Mapped[str | None] = mapped_column(Text)
    last_editor: Mapped[str | None] = mapped_column(Text)
