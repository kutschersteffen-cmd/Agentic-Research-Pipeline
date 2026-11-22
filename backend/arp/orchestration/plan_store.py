"""Postgres store for research plans and the step calls their runs make."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from arp.errors import NotConfigured
from arp.orchestration.plan_check import check_script
from arp.orchestration.plan_interp import dry_run
from arp.orchestration.plan_models import AgentAsk, ResearchPlan, ResearchPlanCall
from arp.schemas.common import new_id


class PlanNotFound(LookupError):
    pass


class PlanNotReplannable(NotConfigured):
    pass


def _checked_dry_run(script: str, previous: list[dict] | None = None, first_seq: int = 1,
                     check: Callable[[list[dict]], list[str]] | None = None) -> list[dict]:
    errors = check_script(script)
    if errors:
        raise ValueError("\n".join(errors))
    try:
        steps = dry_run(script, previous, first_seq)
    except Exception as exc:  # noqa: BLE001 - any dry-run failure is a script error the author must fix
        raise ValueError(str(exc)) from exc
    errors = check(steps) if check else []
    if errors:
        raise ValueError("\n".join(errors))
    return steps


def _row(obj) -> dict[str, Any]:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def _plan_row(plan: ResearchPlan) -> dict[str, Any]:
    row = _row(plan)
    budget = row["budget_usd"]
    return {**row, "version": row["version"] or 1, "previous_scripts": row["previous_scripts"] or [],
            "budget_usd": None if budget is None else float(budget), "planner_cost_usd": float(row["planner_cost_usd"] or 0)}


def _with_source_ask(s: Session, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adds `source_ask: {question, thread_id}` of the ask each plan was drafted from, or None."""
    ids = {r["source_ask_id"] for r in rows if r["source_ask_id"]}
    asks = {a.id: {"question": a.question, "thread_id": a.thread_id}
            for a in s.scalars(select(AgentAsk).where(AgentAsk.id.in_(ids)))} if ids else {}
    return [{**r, "source_ask": asks.get(r["source_ask_id"])} for r in rows]


def _usd(amount: float) -> Decimal:
    return Decimal(repr(amount))  # repr: the float round-trips exactly, so sums stay decimal


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

    def create(self, brief: str, script: str, previous_scripts: list[dict] | None = None,
               check: Callable[[list[dict]], list[str]] | None = None, planner_cost_usd: float = 0.0,
               source_ask_id: str | None = None) -> str:
        """Raises ValueError with the checker's errors when the script is rejected. `previous_scripts` stores the
        plan as already re-planned (the demo plan), at the version after them. `check` adds errors from the dry run.
        `planner_cost_usd` is what the planner's calls for this draft cost. `source_ask_id` is the ask it was drafted
        from."""
        steps = _checked_dry_run(script, check=check)
        plan_id = new_id("plan")
        history = previous_scripts or []
        with Session(self.engine) as s, s.begin():
            s.add(ResearchPlan(id=plan_id, brief=brief, script=script, dry_run=steps, status="draft",
                               created_at=datetime.now(UTC), version=len(history) + 1, previous_scripts=history,
                               planner_cost_usd=_usd(planner_cost_usd), source_ask_id=source_ask_id))
        return plan_id

    def get(self, plan_id: str) -> dict[str, Any]:
        with Session(self.engine) as s:
            plan = s.get(ResearchPlan, plan_id)
            if plan is None:
                raise PlanNotFound(plan_id)
            return _with_source_ask(s, [_plan_row(plan)])[0]

    def list(self) -> list[dict[str, Any]]:
        with Session(self.engine) as s:
            return _with_source_ask(s, [_plan_row(p) for p in s.scalars(select(ResearchPlan).order_by(ResearchPlan.created_at.desc()))])

    def active(self) -> list[tuple[str, str]]:
        """(id, status) of every plan that is `running` or `awaiting_review`, oldest first."""
        with Session(self.engine) as s:
            rows = s.execute(select(ResearchPlan.id, ResearchPlan.status)
                             .where(ResearchPlan.status.in_({"running", "awaiting_review"}))
                             .order_by(ResearchPlan.created_at))
            return [(r.id, r.status) for r in rows]

    def update_script(self, plan_id: str, script: str) -> None:
        """An edit always returns the plan to draft and clears its approval. A re-planned plan keeps the calls kept at
        re-planning: the edited script reads them as `previous` and starts after them."""
        previous, first_seq = kept_calls(self.get(plan_id), self.calls(plan_id))
        steps = _checked_dry_run(script, previous, first_seq)
        self._set(plan_id, script=script, dry_run=steps, status="draft", approved_by=None, approved_at=None)
        with Session(self.engine) as s, s.begin():  # a new script must not reuse an old script's results
            s.execute(delete(ResearchPlanCall).where(ResearchPlanCall.plan_id == plan_id,
                                                     ResearchPlanCall.seq >= first_seq))

    def replan(self, plan_id: str, script: str, user: str | None = None,
               check: Callable[[list[dict]], list[str]] | None = None) -> None:
        """Replace a failed plan's script with one for the remaining work: keeps its done calls (the new script reads
        their results as `previous`), drops failed and cancelled ones, files the old script and error under
        `previous_scripts` and returns the plan to an unapproved draft. Raises ValueError when the script is
        rejected, PlanNotReplannable unless the plan is failed."""
        if self.get(plan_id)["status"] != "failed":
            raise PlanNotReplannable("only a failed plan can be re-planned")
        done = [c for c in self.calls(plan_id) if c["status"] == "done"]
        first_seq = max((c["seq"] for c in done), default=0) + 1  # a kept seq is never reused
        steps = _checked_dry_run(script, [c["result"] for c in done], first_seq, check)
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

    def set_budget(self, plan_id: str, budget_usd: float | None) -> None:
        """A new budget needs a new approval: an approved, done or failed plan returns to draft. Every stored call is
        kept, so a resume reuses the finished steps."""
        with Session(self.engine) as s, s.begin():
            plan = s.get(ResearchPlan, plan_id, with_for_update=True)
            if plan is None:
                raise PlanNotFound(plan_id)
            plan.budget_usd = None if budget_usd is None else _usd(budget_usd)
            if plan.status in {"approved", "done", "failed"}:
                plan.status, plan.approved_by, plan.approved_at = "draft", None, None

    def add_planner_cost(self, plan_id: str, usd: float) -> None:
        with Session(self.engine) as s, s.begin():
            s.execute(update(ResearchPlan).where(ResearchPlan.id == plan_id)
                      .values(planner_cost_usd=ResearchPlan.planner_cost_usd + _usd(usd)))

    def spent_usd(self, plan_id: str) -> float:
        """`estimated_cost_usd` summed over every run the plan started (each attempt, also those a resume, re-plan or
        edit dropped from its calls: found by their launch key) and the runs its calls store, plus the planner's own
        calls."""
        from arp.db.models import Run

        run_ids = select(ResearchPlanCall.run_id).where(ResearchPlanCall.plan_id == plan_id,
                                                        ResearchPlanCall.run_id.is_not(None))
        launched = Run.params["launch_key"].astext.startswith(f"plan:{plan_id}:", autoescape=True)
        with Session(self.engine) as s:
            runs = s.scalar(select(func.coalesce(func.sum(Run.estimated_cost_usd), 0))
                            .where(or_(Run.run_id.in_(run_ids), launched)))
            planner = s.scalar(select(ResearchPlan.planner_cost_usd).where(ResearchPlan.id == plan_id))
        return float(Decimal(runs) + (planner or 0))

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

    def record_call(self, plan_id: str, *, seq: int, kind: str, params: dict, status: str, attempt: int = 1) -> None:
        with Session(self.engine) as s, s.begin():
            s.merge(ResearchPlanCall(plan_id=plan_id, seq=seq, kind=kind, params=params, status=status,
                                     run_id=None, result_ref=None, result=None, started_at=datetime.now(UTC),
                                     attempt=attempt))

    def update_call(self, plan_id: str, seq: int, **values: Any) -> None:
        with Session(self.engine) as s, s.begin():
            call = s.get(ResearchPlanCall, (plan_id, seq))
            for k, v in values.items():
                setattr(call, k, v)

    def calls_awaiting_review(self) -> list[dict[str, Any]]:
        """Every call with status `awaiting_review` of a plan still `awaiting_review`, for the agent inbox. A plan
        cancelled while a gated step finished keeps that call `awaiting_review`, but nothing waits on it."""
        with Session(self.engine) as s:
            rows = s.scalars(select(ResearchPlanCall).join(ResearchPlan, ResearchPlan.id == ResearchPlanCall.plan_id)
                             .where(ResearchPlanCall.status == "awaiting_review",
                                    ResearchPlan.status == "awaiting_review"))
            return [_row(r) for r in rows]

    def calls(self, plan_id: str) -> list[dict[str, Any]]:
        with Session(self.engine) as s:
            rows = s.scalars(select(ResearchPlanCall).where(ResearchPlanCall.plan_id == plan_id)
                             .order_by(ResearchPlanCall.seq))
            return [_row(r) for r in rows]

    def audited_calls(self, plan_id: str) -> list[dict[str, Any]]:
        """`calls`, each with its run's `model` and `estimated_cost_usd`: null for a call without a stored run."""
        from arp.db.models import Run

        calls = self.calls(plan_id)
        run_ids = [c["run_id"] for c in calls if c["run_id"]]
        with Session(self.engine) as s:
            runs = {r.run_id: r for r in s.execute(select(Run.run_id, Run.model, Run.estimated_cost_usd)
                                                   .where(Run.run_id.in_(run_ids)))} if run_ids else {}
        out = []
        for c in calls:
            run = runs.get(c["run_id"])
            cost = run.estimated_cost_usd if run else None
            out.append({**c, "model": run.model if run else None, "estimated_cost_usd": None if cost is None else float(cost)})
        return out
