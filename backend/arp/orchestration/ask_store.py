"""Postgres store for the Agent screen's ask threads (spec agent-panel-code-mode, Phase 7, D10)."""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from arp.orchestration.plan_models import AgentAsk, ResearchPlan

HISTORY_TURNS = 5  # the limit POST /api/ask has
HISTORY_TEXT = 1000


class AskStore:
    def __init__(self, dsn: str):
        from arp.storage.postgres import get_engine

        self.engine = get_engine(dsn)

    def is_thread(self, thread_id: str) -> bool:
        """True when `thread_id` is a thread's first ask; a follow-up's id is not a thread."""
        with Session(self.engine) as s:
            ask = s.get(AgentAsk, thread_id)
            return ask is not None and ask.thread_id == ask.id

    def exists(self, ask_id: str) -> bool:
        with Session(self.engine) as s:
            return s.get(AgentAsk, ask_id) is not None

    def history(self, thread_id: str) -> list[dict[str, str]]:
        """The thread's newest answered asks, oldest first, as `HistoryTurn`s; failed asks are never sent."""
        with Session(self.engine) as s:
            rows = s.scalars(select(AgentAsk).where(AgentAsk.thread_id == thread_id, AgentAsk.tool.is_not(None))
                             .order_by(AgentAsk.created_at.desc()).limit(HISTORY_TURNS)).all()
            return [{"question": a.question[:HISTORY_TEXT], "tool": a.tool,
                     "standalone_question": (a.standalone_question or "")[:HISTORY_TEXT]} for a in reversed(rows)]

    def add(self, *, thread_id: str | None, question: str, asked_by: str, tool: str | None = None,
            standalone_question: str | None = None, response: dict | None = None, error: str | None = None) -> dict:
        """Stores one ask; without `thread_id` it starts a thread of its own."""
        ask_id = str(uuid.uuid4())
        with Session(self.engine) as s, s.begin():
            s.add(AgentAsk(id=ask_id, thread_id=thread_id or ask_id, question=question, asked_by=asked_by, tool=tool,
                           standalone_question=standalone_question, response=response, error=error,
                           created_at=datetime.now(UTC)))
        return self.asks([ask_id])[0]

    def thread(self, thread_id: str) -> list[dict]:
        with Session(self.engine) as s:
            ids = s.scalars(select(AgentAsk.id).where(AgentAsk.thread_id == thread_id).order_by(AgentAsk.created_at)).all()
        return self.asks(list(ids))

    def asks(self, ids: list[str]) -> list[dict]:
        """The asks in `ids` order, each with the plans drafted from it (oldest first). `explorations` stays `[]`
        until explorations can be drafted from an ask (slice 14)."""
        with Session(self.engine) as s:
            rows = {a.id: a for a in s.scalars(select(AgentAsk).where(AgentAsk.id.in_(ids)))}
            plans: dict[str, list[dict]] = {}
            for p in s.scalars(select(ResearchPlan).where(ResearchPlan.source_ask_id.in_(ids)).order_by(ResearchPlan.created_at)):
                plans.setdefault(p.source_ask_id, []).append({"plan_id": p.id, "brief": p.brief, "status": p.status})
            return [{**{c.name: getattr(rows[i], c.name) for c in AgentAsk.__table__.columns},
                     "plans": plans.get(i, []), "explorations": []} for i in ids]

    def threads(self) -> list[dict[str, Any]]:
        """One row per thread, newest first by its first ask's `created_at`."""
        with Session(self.engine) as s:
            asks = s.scalars(select(AgentAsk).order_by(AgentAsk.created_at)).all()
        counts = Counter(a.thread_id for a in asks)
        newest = {a.thread_id: a for a in asks}  # oldest first, so the last one written is the thread's newest
        return [{"thread_id": a.id, "title": a.question[:60], "status": "answered" if newest[a.id].error is None else "failed",
                 "created_at": a.created_at, "asks": counts[a.id]} for a in reversed(asks) if a.thread_id == a.id]
