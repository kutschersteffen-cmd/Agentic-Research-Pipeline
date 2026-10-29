"""Tables of the authoritative layer: versioned values (append-only; rows are only closed or reconfirmed) and one
record per publish."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, Integer, Numeric, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from arp.storage.postgres_models import Base


class AuthoritativeValue(Base):
    __tablename__ = "authoritative_values"
    __table_args__ = (
        Index("uq_authoritative_values_current", "framework_id", "output_column", "company_id", unique=True,
              postgresql_where=text("valid_to IS NULL")),
        Index("ix_authoritative_values_key", "framework_id", "output_column", "company_id", "valid_from"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    framework_id: Mapped[str] = mapped_column(Text)
    output_column: Mapped[str] = mapped_column(Text)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id"))
    value: Mapped[object] = mapped_column(JSONB, nullable=True)
    canonical_value: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    period_end: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text)  # value | no_value
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    derivation: Mapped[dict] = mapped_column(JSONB)
    framework_version: Mapped[int] = mapped_column(Integer)
    dataset_as_of: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_id: Mapped[str] = mapped_column(Text)
    published_by: Mapped[str] = mapped_column(Text)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("authoritative_values.id"), nullable=True)
    reconfirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthoritativePublish(Base):
    __tablename__ = "authoritative_publishes"

    snapshot_id: Mapped[str] = mapped_column(Text, primary_key=True)
    framework_id: Mapped[str] = mapped_column(Text, index=True)
    framework_version: Mapped[int] = mapped_column(Integer)
    dataset_id: Mapped[str] = mapped_column(Text)
    dataset_as_of: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_by: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
