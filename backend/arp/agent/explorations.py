"""Explorations: a question, the code written for it, and what the sandbox returned (spec agent-panel-code-mode,
Phase 4). Results stay `exploratory` until a person accepts them; nothing in the plan lane reads them."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from arp import standins
from arp.agent import sandbox
from arp.agent.models import AgentExploration
from arp.api.auth import Principal
from arp.config import Settings
from arp.errors import NotConfigured


def _out(row: AgentExploration) -> dict[str, Any]:
    out = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    out["id"] = str(row.id)
    out["cost_usd"] = float(row.cost_usd or 0)
    out["label"] = "accepted" if row.accepted_at else "exploratory"
    return out


class ExplorationStore:
    def __init__(self, dsn: str):
        from arp.storage.postgres import get_engine

        self.engine = get_engine(dsn)

    def add(self, *, question: str, code: str, run: dict[str, Any], model: str | None, cost_usd: float = 0.0) -> dict:
        row = AgentExploration(
            id=uuid.uuid4(), question=question, code=code, status=run["status"], result=run["result"],
            error=run["error"], tool_calls=run["tool_calls"], model=model, cost_usd=Decimal(repr(cost_usd)),
            created_at=datetime.now(UTC))
        with Session(self.engine, expire_on_commit=False) as s, s.begin():
            s.add(row)
        return _out(row)


def write_code(settings: Settings, question: str) -> tuple[str, str]:
    """(code, model) for the question: entry 1 of the stand-in explore.json (the model call comes with retries)."""
    folder = settings.standins_dir
    if folder is None:
        raise NotConfigured("Explorations have no code writer configured yet.")
    return standins.exploration_code(folder, question), "stand-in"


async def explore(store: ExplorationStore, settings: Settings, question: str, principal: Principal) -> dict:
    """Writes code for the question, runs it in the sandbox and stores the outcome, whatever it is."""
    code, model = write_code(settings, question)
    run = await sandbox.execute(code, principal, settings)
    return store.add(question=question, code=code, run=run, model=model)
