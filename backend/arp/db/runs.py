"""Postgres-backed RunStore: a run's manifest, companies, results, errors and review rows live in
the run/review tables. Side artifacts with no table (snapshots, events, restatement candidates,
schema.json, regrounds.jsonl, ...) stay files under `runs_dir/<run_id>/`, reached via `run_dir`."""

from __future__ import annotations

import math
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from arp.db.models import (
    Company,
    DecisionKind,
    ReviewCosign,
    ReviewDecision,
    ReviewItem,
    Run,
    RunCompany,
    RunError,
    RunResult,
    RunStatus,
)
from arp.db.session import transaction
from arp.schemas.common import CompanyRef, RunManifest, now_iso
from arp.storage.jsonl_io import append_jsonl, read_jsonl
from arp.storage.postgres_projection_config import ProjectionConfig
from arp.storage.run_store import _TERMINAL_STATUSES, LegacyRunStore, done_keys_from_rows, sync_projections
from arp.universe import resolve_universe

_DECISIONS = {d.value for d in DecisionKind}
# Decision-log rows that are not review-queue decisions, so carry no DecisionKind: emerging-theme
# candidate actions (arp/emerging_themes/pipeline.py), which have `action` and no `decision`.
_NON_REVIEW_ACTIONS = {"promote", "reject", "disconfirm"}


def _jsonb_safe(value):
    """What Postgres jsonb can store: NaN/±Infinity become None and NUL is stripped from strings
    (keys too). The file store wrote both; jsonb refuses them, which would fail a whole batch."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {_jsonb_safe(k): _jsonb_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonb_safe(v) for v in value]
    return value


def _decision_kind(row: dict) -> DecisionKind | None:
    decision = row.get("decision")
    if decision in _DECISIONS:
        return DecisionKind(decision)
    if decision is None and row.get("action") in _NON_REVIEW_ACTIONS:
        return None
    raise ValueError(f"not a review decision: {decision!r}")


def _ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


class RunStore:
    def __init__(self, dsn: str, runs_dir: Path, projection_config: ProjectionConfig | None = None) -> None:
        self.dsn = dsn
        self.runs_dir = runs_dir
        self._files = LegacyRunStore(runs_dir)  # side artifacts only
        self._projection_config = projection_config
        self._local = threading.local()  # run_id -> the session holding that run's lock, per thread

    def _held(self) -> dict[str, Session]:
        if not hasattr(self._local, "sessions"):
            self._local.sessions = {}
        return self._local.sessions

    @contextmanager
    def _tx(self, run_id: str) -> Iterator[Session]:
        """The run's lock-holding session when this thread holds `lock(run_id)` (another connection
        would wait on that row lock forever), else a fresh transaction."""
        held = self._held().get(run_id)
        if held is not None:
            yield held
        else:
            with transaction(self.dsn) as s:
                yield s

    @staticmethod
    def _ensure_run(s: Session, run_id: str) -> None:
        # Rows may be appended before the manifest is saved; run_type "" marks "no manifest yet".
        s.execute(insert(Run).values(run_id=run_id, run_type="", status=RunStatus.PENDING).on_conflict_do_nothing())

    @staticmethod
    def _universe_company(run_id: str, universe_id):
        return (
            select(RunCompany.company_id)
            .where(RunCompany.run_id == run_id, RunCompany.ref["company_id"].astext == str(universe_id))
            .limit(1)
            .scalar_subquery()
        )

    @contextmanager
    def lock(self, run_id: str) -> Iterator[None]:
        """Serializes a read-modify-write cycle against one run (JobManager._update, decide, ...):
        a transaction holding `SELECT ... FOR UPDATE` on the runs row, across processes too.
        Re-entrant per thread; every store call this thread makes for the run inside it uses that
        transaction, so its writes commit when the outermost lock exits. Re-entrancy and session
        reuse are per RunStore instance: writing the same run through another instance on the same
        thread while this lock is held waits on the row lock forever (deadlock)."""
        held = self._held()
        if run_id in held:
            yield
            return
        with transaction(self.dsn) as s:
            self._ensure_run(s, run_id)
            s.execute(select(Run.run_id).where(Run.run_id == run_id).with_for_update())
            held[run_id] = s
            try:
                yield
            finally:
                del held[run_id]

    def run_dir(self, run_id: str) -> Path:
        return self._files.run_dir(run_id)

    # --- rows -----------------------------------------------------------------

    def read_results(self, run_id: str) -> list[dict]:
        with self._tx(run_id) as s:
            return list(s.scalars(select(RunResult.result).where(RunResult.run_id == run_id).order_by(RunResult.id)))

    def append_result(self, run_id: str, row: dict) -> None:
        """Re-appending a `_key` already stored is a no-op. A row without `_key` (replication
        steps, calibration flags, ...) is always appended, under a key of its own."""
        row = _jsonb_safe(row)
        key = row.get("_key") or f"~{uuid.uuid4().hex}"
        with self._tx(run_id) as s:
            self._ensure_run(s, run_id)
            s.execute(
                insert(RunResult)
                .values(run_id=run_id, result_key=key, company_id=self._universe_company(run_id, key), result=row)
                .on_conflict_do_nothing(constraint="uq_run_results_key")
            )

    def read_errors(self, run_id: str) -> list[dict]:
        with self._tx(run_id) as s:
            return list(s.scalars(select(RunError.error).where(RunError.run_id == run_id).order_by(RunError.id)))

    def append_error(self, run_id: str, row: dict) -> None:
        row = _jsonb_safe(row)
        with self._tx(run_id) as s:
            self._ensure_run(s, run_id)
            company = self._universe_company(run_id, row.get("key") or row.get("company_id"))
            s.execute(insert(RunError).values(run_id=run_id, company_id=company, error=row))

    def read_review_queue(self, run_id: str) -> list[dict]:
        with self._tx(run_id) as s:
            return list(s.scalars(select(ReviewItem.payload).where(ReviewItem.run_id == run_id).order_by(ReviewItem.id)))

    def append_review_item(self, run_id: str, row: dict) -> None:
        """Requires `item_key`; re-queueing a key replaces its row. `company_id` is the company's
        UUID, or a universe id resolved through the run's companies; NULL when neither matches."""
        row = _jsonb_safe(row)
        cid = row.get("company_id")
        try:
            company = select(Company.id).where(Company.id == uuid.UUID(str(cid))).scalar_subquery()
        except ValueError:
            company = self._universe_company(run_id, cid)
        with self._tx(run_id) as s:
            self._ensure_run(s, run_id)
            stmt = insert(ReviewItem).values(
                run_id=run_id, item_key=row["item_key"], company_id=company,
                observation_id=row.get("observation_id"), payload=row,
            )
            s.execute(
                stmt.on_conflict_do_update(
                    constraint="uq_review_items_key",
                    set_={"payload": stmt.excluded.payload, "company_id": stmt.excluded.company_id},
                )
            )

    def _item_id(self, run_id: str, row: dict):
        return (
            select(ReviewItem.id).where(ReviewItem.run_id == run_id, ReviewItem.item_key == row.get("item_key")).scalar_subquery()
        )

    def read_decisions(self, run_id: str) -> list[dict]:
        with self._tx(run_id) as s:
            return list(s.scalars(select(ReviewDecision.row).where(ReviewDecision.run_id == run_id).order_by(ReviewDecision.id)))

    def append_decision_row(self, run_id: str, row: dict) -> None:
        """Raises ValueError for a `decision` that is no DecisionKind; only the non-review
        actions in _NON_REVIEW_ACTIONS are stored without one."""
        row = _jsonb_safe(row)
        decision = _decision_kind(row)
        with self._tx(run_id) as s:
            self._ensure_run(s, run_id)
            s.execute(
                insert(ReviewDecision).values(
                    run_id=run_id, review_item_id=self._item_id(run_id, row),
                    decision=decision,
                    reviewer=row.get("reviewer"), user_id=row.get("user_id"), role=row.get("role"),
                    edited_value=row.get("edited_value"), comment=row.get("comment"), row=row,
                )
            )

    def read_cosigns(self, run_id: str) -> list[dict]:
        with self._tx(run_id) as s:
            return list(s.scalars(select(ReviewCosign.row).where(ReviewCosign.run_id == run_id).order_by(ReviewCosign.id)))

    def append_cosign(self, run_id: str, row: dict) -> None:
        row = _jsonb_safe(row)
        with self._tx(run_id) as s:
            self._ensure_run(s, run_id)
            s.execute(
                insert(ReviewCosign).values(
                    run_id=run_id, review_item_id=self._item_id(run_id, row), reviewer=row.get("name"),
                    user_id=row.get("user_id"), role=row.get("role"), row=row,
                )
            )

    # No table for these: files under run_dir.
    def read_restatements(self, run_id: str) -> list[dict]:
        return self._files.read_restatements(run_id)

    def append_restatement(self, run_id: str, row: dict) -> None:
        self._files.append_restatement(run_id, row)

    def read_events(self, run_id: str) -> list[dict]:
        return self._files.read_events(run_id)

    def append_event(self, run_id: str, row: dict) -> None:
        self._files.append_event(run_id, row)

    def read_snapshot(self, run_id: str, snapshot_id: str) -> dict | None:
        return self._files.read_snapshot(run_id, snapshot_id)

    def save_snapshot(self, run_id: str, snapshot_id: str, data: dict) -> None:
        self._files.save_snapshot(run_id, snapshot_id, data)

    def done_keys(self, run_id: str, *, include_errors: bool = False) -> set[str]:
        return done_keys_from_rows(self.read_results(run_id), self.read_errors(run_id) if include_errors else ())

    # --- companies ------------------------------------------------------------

    def save_companies(self, run_id: str, companies: list[CompanyRef]) -> list[CompanyRef]:
        """Replaces the run's companies, resolving each ref without `entity_id` through the
        registry. An identity conflict is recorded as a run error and the ref left out.
        Returns the saved refs, each with `entity_id`."""
        saved: list[CompanyRef] = []
        with self._tx(run_id) as s:
            self._ensure_run(s, run_id)
            s.execute(update(Run).where(Run.run_id == run_id).values(companies_saved_at=func.now()))
            s.execute(delete(RunCompany).where(RunCompany.run_id == run_id))
            for c in companies:
                c = CompanyRef.model_validate(_jsonb_safe(c.model_dump(mode="json")))  # NUL-free before the registry sees it
                if c.entity_id is None:
                    resolved, conflicts = resolve_universe([c], s)
                    for conflict in conflicts:
                        s.execute(insert(RunError).values(run_id=run_id, error=conflict))
                    if not resolved:
                        continue
                    c = resolved[0]
                ref = c.model_dump(mode="json")
                # ponytail: two refs resolving to one company keep the first; key run_companies by ordinal if that matters
                inserted = s.execute(
                    insert(RunCompany)
                    .values(run_id=run_id, company_id=c.entity_id, ordinal=len(saved), ref=ref)
                    .on_conflict_do_nothing()
                    .returning(RunCompany.company_id)
                ).first()
                if inserted is not None:
                    saved.append(c)
        return saved

    def load_companies(self, run_id: str) -> list[CompanyRef] | None:
        """The companies a run was created over ([] when every one was an identity conflict), or
        None for a run that never saved any (voting, older runs) and so cannot be resumed."""
        if not self.has_companies(run_id):
            return None
        with self._tx(run_id) as s:
            refs = s.scalars(select(RunCompany.ref).where(RunCompany.run_id == run_id).order_by(RunCompany.ordinal)).all()
        return [CompanyRef.model_validate(r) for r in refs]

    def has_companies(self, run_id: str) -> bool:
        with self._tx(run_id) as s:
            return s.scalar(select(Run.companies_saved_at).where(Run.run_id == run_id)) is not None

    # --- manifests ------------------------------------------------------------

    def save_manifest(self, manifest: RunManifest) -> None:
        manifest.updated_at = now_iso()
        values = manifest.model_dump(mode="json")
        values.update(
            created_at=_ts(manifest.created_at),
            updated_at=_ts(manifest.updated_at),
            status=RunStatus(manifest.status.value),
            estimated_cost_usd=Decimal(repr(manifest.estimated_cost_usd)),  # repr: the float round-trips exactly
        )
        stmt = insert(Run).values(**values)
        with self._tx(manifest.run_id) as s:
            s.execute(stmt.on_conflict_do_update(index_elements=[Run.run_id], set_={k: stmt.excluded[k] for k in values if k != "run_id"}))
        if self._projection_config is not None and manifest.status in _TERMINAL_STATUSES:
            sync_projections(self._projection_config, self, manifest.run_id)

    @staticmethod
    def _manifest(run: Run) -> RunManifest:
        return RunManifest(
            run_id=run.run_id, run_type=run.run_type, created_at=_iso(run.created_at), updated_at=_iso(run.updated_at),
            status=run.status.value, params=run.params or {}, company_count=run.company_count,
            completed_count=run.completed_count, failed_count=run.failed_count, review_count=run.review_count,
            input_tokens=run.input_tokens, output_tokens=run.output_tokens,
            estimated_cost_usd=float(run.estimated_cost_usd or 0), model=run.model, verifier_model=run.verifier_model,
            error=run.error, cancel_requested=run.cancel_requested,
        )

    def load_manifest(self, run_id: str) -> RunManifest | None:
        with self._tx(run_id) as s:
            run = s.get(Run, run_id, populate_existing=True)
            return self._manifest(run) if run is not None and run.run_type else None

    def list_runs(self, run_type: str | None = None) -> list[RunManifest]:
        """Newest first by created_at."""
        query = select(Run).where(Run.run_type != "").order_by(Run.created_at.desc())
        if run_type:
            query = query.where(Run.run_type == run_type)
        with transaction(self.dsn) as s:
            return [self._manifest(r) for r in s.scalars(query)]

    def extraction_runs(self) -> list[RunManifest]:
        """Non-trial extraction runs, newest first."""
        return [m for m in self.list_runs("extraction") if not m.params.get("trial")]

    read_jsonl = staticmethod(read_jsonl)
    append_jsonl = staticmethod(append_jsonl)
