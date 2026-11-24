"""Postgres store of the agent board (spec agent-board, "Data" and "API").

Every write takes a transaction-scoped advisory lock on its board, so positions stay `0 … n-1` with no gaps.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from arp.agent_board.models import AgentBoardBlock, AgentBoardVersion

MAX_BLOCKS = 50


class BlockNotFound(LookupError):
    pass


class BoardFull(Exception):
    pass


class NothingToUndo(Exception):
    pass


def _row(obj) -> dict[str, Any]:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _clamp(p: int, n: int) -> int:
    return max(0, min(p, n))


class BoardStore:
    def __init__(self, dsn: str):
        from arp.storage.postgres import get_engine

        self.engine = get_engine(dsn)

    def thread_exists(self, thread_kind: str, thread_id: str) -> bool:
        if thread_kind == "exploration":
            from arp.agent.models import AgentExploration

            try:
                key = uuid.UUID(thread_id)
            except ValueError:
                return False
            with Session(self.engine) as s:
                return s.get(AgentExploration, key) is not None
        from arp.orchestration.plan_models import ResearchPlan

        with Session(self.engine) as s:
            return s.get(ResearchPlan, thread_id) is not None

    def thread_data(self, thread_kind: str, thread_id: str) -> dict:
        """The thread data for a draw (spec "Drawing"): a plan's, or an exploration's question, status and result."""
        if thread_kind == "exploration":
            from arp.agent.models import AgentExploration

            with Session(self.engine) as s:
                e = s.get(AgentExploration, uuid.UUID(thread_id))
                return {"question": e.question, "status": e.status, "result": e.result}
        return self.plan_data(thread_id)

    def plan_data(self, plan_id: str) -> dict:
        """The plan's thread data for a draw (spec "Drawing"): brief, status and its stored calls by `seq`."""
        from arp.orchestration.plan_models import ResearchPlan, ResearchPlanCall

        with Session(self.engine) as s:
            plan = s.get(ResearchPlan, plan_id)
            calls = s.scalars(select(ResearchPlanCall).where(ResearchPlanCall.plan_id == plan_id)
                              .order_by(ResearchPlanCall.seq))
            steps = [{"seq": c.seq, "kind": c.kind, "params": c.params, "status": c.status, "run_id": c.run_id,
                      "result": c.result} for c in calls]
            return {"brief": plan.brief, "status": plan.status, "steps": steps}

    def _lock(self, s: Session, thread_kind: str, thread_id: str) -> None:
        s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"agent_board:{thread_kind}:{thread_id}"})

    def _block(self, s: Session, thread_kind: str, thread_id: str, block_id: str) -> AgentBoardBlock:
        b = s.get(AgentBoardBlock, block_id)
        if b is None or (b.thread_kind, b.thread_id) != (thread_kind, thread_id):
            raise BlockNotFound(block_id)
        return b

    def _version(self, s: Session, b: AgentBoardBlock, now: datetime) -> None:
        s.add(AgentBoardVersion(block_id=b.id, version=b.version, kind=b.kind, title=b.title, source=b.source,
                                origin=b.origin, unverified=b.unverified, created_at=now))

    def _shift(self, s: Session, thread_kind: str, thread_id: str, lo: int, hi: int | None, by: int) -> None:
        """Adds `by` to the position of every block with `lo <= position` (and `position <= hi` when given)."""
        where = [AgentBoardBlock.thread_kind == thread_kind, AgentBoardBlock.thread_id == thread_id,
                 AgentBoardBlock.position >= lo]
        if hi is not None:
            where.append(AgentBoardBlock.position <= hi)
        s.execute(update(AgentBoardBlock).where(*where).values(position=AgentBoardBlock.position + by))

    def _count(self, s: Session, thread_kind: str, thread_id: str) -> int:
        return s.scalar(select(func.count()).select_from(AgentBoardBlock).where(
            AgentBoardBlock.thread_kind == thread_kind, AgentBoardBlock.thread_id == thread_id))

    def blocks(self, thread_kind: str, thread_id: str) -> list[dict]:
        with Session(self.engine) as s:
            rows = s.scalars(select(AgentBoardBlock).where(
                AgentBoardBlock.thread_kind == thread_kind, AgentBoardBlock.thread_id == thread_id,
            ).order_by(AgentBoardBlock.position))
            return [_row(b) for b in rows]

    def create(self, thread_kind: str, thread_id: str, kind: str, title: str, source: Any, origin: str = "person",
               unverified: list | None = None, position: int | None = None) -> dict:
        now = datetime.now(UTC)
        with Session(self.engine) as s, s.begin():
            self._lock(s, thread_kind, thread_id)
            n = self._count(s, thread_kind, thread_id)
            if n >= MAX_BLOCKS:
                raise BoardFull
            pos = n if position is None else _clamp(position, n)
            self._shift(s, thread_kind, thread_id, pos, None, 1)
            b = AgentBoardBlock(id=str(uuid.uuid4()), thread_kind=thread_kind, thread_id=thread_id, position=pos,
                                kind=kind, title=title, source=source, version=1, origin=origin,
                                unverified=unverified or [], created_at=now, updated_at=now)
            s.add(b)
            self._version(s, b, now)
            s.flush()
            return _row(b)

    def patch(self, thread_kind: str, thread_id: str, block_id: str, title: str | None = None,
              source: Any = None, position: int | None = None, unverified: list | None = None) -> dict:
        """A changed `title` or `source` makes a new version; a `source` change sets `origin: person` and
        `unverified` (when given).
        `position` moves the block (clamped), without a new version."""
        now = datetime.now(UTC)
        with Session(self.engine) as s, s.begin():
            self._lock(s, thread_kind, thread_id)
            b = self._block(s, thread_kind, thread_id, block_id)
            if position is not None:
                to = _clamp(position, self._count(s, thread_kind, thread_id) - 1)
                if to < b.position:
                    self._shift(s, thread_kind, thread_id, to, b.position - 1, 1)
                elif to > b.position:
                    self._shift(s, thread_kind, thread_id, b.position + 1, to, -1)
                s.execute(update(AgentBoardBlock).where(AgentBoardBlock.id == b.id).values(position=to))
                s.refresh(b)
            changed = False
            if title is not None and title != b.title:
                b.title, changed = title, True
            if source is not None and source != b.source:
                b.source, b.origin, changed = source, "person", True
                if unverified is not None:
                    b.unverified = unverified
            if changed:
                b.version += 1
                b.updated_at = now
                self._version(s, b, now)
            s.flush()
            return _row(b)

    def redraw(self, thread_kind: str, thread_id: str, block_id: str, kind: str, title: str, source: Any,
               unverified: list) -> dict:
        """The agent's draft as the block's next version (its kind may change); position unchanged."""
        now = datetime.now(UTC)
        with Session(self.engine) as s, s.begin():
            self._lock(s, thread_kind, thread_id)
            b = self._block(s, thread_kind, thread_id, block_id)
            b.kind, b.title, b.source, b.origin, b.unverified = kind, title, source, "agent", unverified
            b.version += 1
            b.updated_at = now
            self._version(s, b, now)
            s.flush()
            return _row(b)

    def undo(self, thread_kind: str, thread_id: str, block_id: str) -> dict:
        """Copies version v - 1 into a new version v + 1."""
        now = datetime.now(UTC)
        with Session(self.engine) as s, s.begin():
            self._lock(s, thread_kind, thread_id)
            b = self._block(s, thread_kind, thread_id, block_id)
            if b.version == 1:
                raise NothingToUndo
            prev = s.get(AgentBoardVersion, (b.id, b.version - 1))
            b.kind, b.title, b.source, b.origin, b.unverified = prev.kind, prev.title, prev.source, prev.origin, prev.unverified
            b.version += 1
            b.updated_at = now
            self._version(s, b, now)
            s.flush()
            return _row(b)

    def delete(self, thread_kind: str, thread_id: str, block_id: str) -> None:
        with Session(self.engine) as s, s.begin():
            self._lock(s, thread_kind, thread_id)
            b = self._block(s, thread_kind, thread_id, block_id)
            pos = b.position
            s.execute(delete(AgentBoardVersion).where(AgentBoardVersion.block_id == b.id))
            s.delete(b)
            s.flush()
            self._shift(s, thread_kind, thread_id, pos + 1, None, -1)
