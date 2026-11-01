"""Tables of the Research Orchestrator: one row per plan script, one per step call it made."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from arp.storage.postgres_models import Base


class ResearchPlan(Base):
    __tablename__ = "research_plans"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    brief: Mapped[str] = mapped_column(Text)
    script: Mapped[str] = mapped_column(Text)
    dry_run: Mapped[list] = mapped_column(JSONB)  # [{seq, kind, params, depends_on}]
    status: Mapped[str] = mapped_column(Text)  # draft|approved|running|awaiting_review|done|failed|cancelled
    approved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ResearchPlanCall(Base):
    __tablename__ = "research_plan_calls"

    plan_id: Mapped[str] = mapped_column(Text, ForeignKey("research_plans.id", ondelete="CASCADE"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text)  # pending|running|awaiting_review|done|failed|cancelled
    run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_ref: Mapped[str | None] = mapped_column(Text, nullable=True)  # sync kinds: e.g. index:<id>@<date>
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # what the script saw; reused on resume
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
