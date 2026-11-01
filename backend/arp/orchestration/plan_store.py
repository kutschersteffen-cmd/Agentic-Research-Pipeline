"""Postgres store for research plans and the step calls their runs make."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from arp.orchestration.plan_check import check_script
from arp.orchestration.plan_interp import dry_run
from arp.orchestration.plan_models import ResearchPlan, ResearchPlanCall
from arp.schemas.common import new_id


class PlanNotFound(LookupError):
    pass


def _checked_dry_run(script: str) -> list[dict]:
    errors = check_script(script)
    if errors:
        raise ValueError("\n".join(errors))
    return dry_run(script)


def _row(obj) -> dict[str, Any]:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


class PlanStore:
    def __init__(self, dsn: str):
        from arp.storage.postgres import get_engine

        self.dsn = dsn  # run_lease takes its advisory lock on this
        self.engine = get_engine(dsn)

    def create(self, brief: str, script: str) -> str:
        """Raises ValueError with the checker's errors when the script is rejected."""
        steps = _checked_dry_run(script)
        plan_id = new_id("plan")
        with Session(self.engine) as s, s.begin():
            s.add(ResearchPlan(id=plan_id, brief=brief, script=script, dry_run=steps, status="draft",
                               created_at=datetime.now(UTC)))
        return plan_id

    def get(self, plan_id: str) -> dict[str, Any]:
        with Session(self.engine) as s:
            plan = s.get(ResearchPlan, plan_id)
            if plan is None:
                raise PlanNotFound(plan_id)
            return _row(plan)

    def list(self) -> list[dict[str, Any]]:
        with Session(self.engine) as s:
            return [_row(p) for p in s.scalars(select(ResearchPlan).order_by(ResearchPlan.created_at.desc()))]

    def update_script(self, plan_id: str, script: str) -> None:
        """An edit always returns the plan to draft and clears its approval."""
        steps = _checked_dry_run(script)
        self._set(plan_id, script=script, dry_run=steps, status="draft", approved_by=None, approved_at=None)

    def approve(self, plan_id: str, user: str) -> None:
        self._set(plan_id, status="approved", approved_by=user, approved_at=datetime.now(UTC))

    def set_status(self, plan_id: str, status: str, error: str | None = None) -> None:
        self._set(plan_id, status=status, error=error)

    def _set(self, plan_id: str, **values: Any) -> None:
        with Session(self.engine) as s, s.begin():
            plan = s.get(ResearchPlan, plan_id)
            if plan is None:
                raise PlanNotFound(plan_id)
            for k, v in values.items():
                setattr(plan, k, v)

    def record_call(self, plan_id: str, *, seq: int, kind: str, params: dict, status: str) -> None:
        with Session(self.engine) as s, s.begin():
            s.merge(ResearchPlanCall(plan_id=plan_id, seq=seq, kind=kind, params=params, status=status,
                                     run_id=None, result_ref=None, result=None, started_at=datetime.now(UTC)))

    def update_call(self, plan_id: str, seq: int, **values: Any) -> None:
        with Session(self.engine) as s, s.begin():
            call = s.get(ResearchPlanCall, (plan_id, seq))
            for k, v in values.items():
                setattr(call, k, v)

    def calls(self, plan_id: str) -> list[dict[str, Any]]:
        with Session(self.engine) as s:
            rows = s.scalars(select(ResearchPlanCall).where(ResearchPlanCall.plan_id == plan_id)
                             .order_by(ResearchPlanCall.seq))
            return [_row(r) for r in rows]
