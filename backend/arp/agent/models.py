"""The explorations table (spec agent-panel-code-mode, Phase 4)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, Numeric, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from arp.storage.postgres_models import Base


class AgentExploration(Base):
    __tablename__ = "agent_explorations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)  # done | failed | timeout
    result: Mapped[object | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[list] = mapped_column(JSONB)  # [{capability_id, args, result_bytes}]
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    miniapp_html: Mapped[str | None] = mapped_column(Text, nullable=True)  # Phase 5: written by "Show as mini-app"
