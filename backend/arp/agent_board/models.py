"""Tables of the agent board: one row per block, one per version of it (spec agent-board, "Data")."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from arp.storage.postgres_models import Base


class AgentBoardBlock(Base):
    __tablename__ = "agent_board_blocks"
    __table_args__ = (Index("ix_agent_board_blocks_board", "thread_kind", "thread_id", "position"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    thread_kind: Mapped[str] = mapped_column(Text)  # plan | exploration
    thread_id: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text)  # note | table | chart | flow
    title: Mapped[str] = mapped_column(Text)
    source: Mapped[object] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer)
    origin: Mapped[str] = mapped_column(Text)  # person | agent
    unverified: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentBoardVersion(Base):
    __tablename__ = "agent_board_versions"

    block_id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    source: Mapped[object] = mapped_column(JSONB)
    origin: Mapped[str] = mapped_column(Text)
    unverified: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
