"""Postgres store for research plans and the step calls their runs make."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from arp.orchestration.plan_check import check_script
from arp.orchestration.plan_interp import dry_run
from arp.orchestration.plan_models import ResearchPlan, ResearchPlanCall
from arp.schemas.common import new_id


class PlanNotFound(LookupError):
    pass


class PlanNotReplannable(RuntimeError):
    pass


def _checked_dry_run(script: str, previous: list[dict] | None = None, first_seq: int = 1) -> list[dict]:
    errors = check_script(script)
    if errors:
        raise ValueError("\n".join(errors))
    try:
        return dry_run(script, previous, first_seq)
    except Exception as exc:  # noqa: BLE001 - any dry-run failure is a script error the author must fix
        raise ValueError(str(exc)) from exc


def _row(obj) -> dict[str, Any]:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _plan_row(plan: ResearchPlan) -> dict[str, Any]:
    row = _row(plan)
    return {**row, "version": row["version"] or 1, "previous_scripts": row["previous_scripts"] or []}


def kept_calls(plan: dict[str, Any], calls: list[dict[str, Any]]) -> tuple[list[dict] | None, int]:
    """A re-planned plan's `previous` (results of the calls kept at re-planning) and its first new seq.
    A plan never re-planned has no `previous` and starts at 1."""
    if plan["version"] == 1:
        return None, 1
    # The dry run stored at re-planning starts right after the kept calls.
    first = plan["dry_run"][0]["seq"] if plan["dry_run"] else max((c["seq"] for c in calls), default=0) + 1
    return [c["result"] for c in calls if c["seq"] < first and c["status"] == "done"], first


class PlanStore:
    def __init__(self, dsn: str):
        from arp.storage.postgres import get_engine

        self.dsn = dsn  # run_lease takes its advisory lock on this
        self.engine = get_engine(dsn)

    def create(self, brief: str, script: str, previous_scripts: list[dict] | None = None) -> str:
        """Raises ValueError with the checker's errors when the script is rejected. `previous_scripts` stores the
        plan as already re-planned (the demo plan), at the version after them."""
        steps = _checked_dry_run(script)
        plan_id = new_id("plan")
        history = previous_scripts or []
        with Session(self.engine) as s, s.begin():
            s.add(ResearchPlan(id=plan_id, brief=brief, script=script, dry_run=steps, status="draft",
                               created_at=datetime.now(UTC), version=len(history) + 1, previous_scripts=history))
        return plan_id

    def get(self, plan_id: str) -> dict[str, Any]:
        with Session(self.engine) as s:
            plan = s.get(ResearchPlan, plan_id)
            if plan is None:
                raise PlanNotFound(plan_id)
            return _plan_row(plan)

    def list(self) -> list[dict[str, Any]]:
        with Session(self.engine) as s:
            return [_plan_row(p) for p in s.scalars(select(ResearchPlan).order_by(ResearchPlan.created_at.desc()))]

    def update_script(self, plan_id: str, script: str) -> None:
        """An edit always returns the plan to draft and clears its approval."""
        steps = _checked_dry_run(script)
        self._set(plan_id, script=script, dry_run=steps, status="draft", approved_by=None, approved_at=None)
        with Session(self.engine) as s, s.begin():  # a new script must not reuse an old script's results
            s.execute(delete(ResearchPlanCall).where(ResearchPlanCall.plan_id == plan_id))

    def replan(self, plan_id: str, script: str, user: str | None = None) -> None:
        """Replace a failed plan's script with one for the remaining work: keeps its done calls (the new script reads
        their results as `previous`), drops failed and cancelled ones, files the old script and error under
        `previous_scripts` and returns the plan to an unapproved draft. Raises ValueError when the script is
        rejected, PlanNotReplannable unless the plan is failed."""
        if self.get(plan_id)["status"] != "failed":
            raise PlanNotReplannable("only a failed plan can be re-planned")
        done = [c for c in self.calls(plan_id) if c["status"] == "done"]
        first_seq = max((c["seq"] for c in done), default=0) + 1  # a kept seq is never reused
        steps = _checked_dry_run(script, [c["result"] for c in done], first_seq)
        with Session(self.engine) as s, s.begin():
            plan = s.get(ResearchPlan, plan_id, with_for_update=True)
            if plan.status != "failed":  # changed while the planner ran
                raise PlanNotReplannable("only a failed plan can be re-planned")
            s.execute(delete(ResearchPlanCall).where(ResearchPlanCall.plan_id == plan_id,
                                                     ResearchPlanCall.status != "done"))
            version = plan.version or 1
            plan.previous_scripts = [*(plan.previous_scripts or []), {
                "version": version, "script": plan.script, "error": plan.error,
                "replanned_at": datetime.now(UTC).isoformat(), "replanned_by": user}]
            plan.script, plan.dry_run, plan.version = script, steps, version + 1
            plan.status, plan.approved_by, plan.approved_at, plan.error = "draft", None, None, None

    def approve(self, plan_id: str, user: str) -> None:
        self._set(plan_id, status="approved", approved_by=user, approved_at=datetime.now(UTC))

    def claim(self, plan_id: str, from_statuses: set[str], to: str) -> bool:
        """Atomically move the plan to `to` if it is in one of `from_statuses`; False when it was not."""
        with Session(self.engine) as s, s.begin():
            done = s.execute(update(ResearchPlan).where(ResearchPlan.id == plan_id,
                                                        ResearchPlan.status.in_(from_statuses)).values(status=to))
            return done.rowcount == 1

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
