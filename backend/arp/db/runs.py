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

from arp.db import observations as observations_db
from arp.db.models import (
    Company,
    DecisionKind,
    Document,
    ReviewCosign,
    ReviewDecision,
    ReviewItem,
    Run,
    RunCompany,
    RunError,
    RunHeldDocument,
    RunResult,
    RunStatus,
)
from arp.db.observations import ObservationIn
from arp.db.session import transaction
from arp.db.to_observations import review_target
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
        with self._tx(run_id) as s:
            self._insert_result(s, run_id, _jsonb_safe(row))

    def _insert_result(self, s: Session, run_id: str, row: dict, company_id=None) -> bool:
        """False when the row's `_key` was already stored."""
        key = row.get("_key") or f"~{uuid.uuid4().hex}"
        self._ensure_run(s, run_id)
        return s.execute(
            insert(RunResult)
            .values(run_id=run_id, result_key=key, company_id=company_id or self._universe_company(run_id, key), result=row)
            .on_conflict_do_nothing(constraint="uq_run_results_key")
            .returning(RunResult.id)
        ).first() is not None

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
        with self._tx(run_id) as s:
            self._insert_review_item(s, run_id, _jsonb_safe(row))

    def _insert_review_item(
        self, s: Session, run_id: str, row: dict, observation_id: int | None = None, company_id=None
    ) -> None:
        """`company_id`, when given, is the company's UUID already known to the caller."""
        cid = row.get("company_id")
        try:
            company = company_id or select(Company.id).where(Company.id == uuid.UUID(str(cid))).scalar_subquery()
        except ValueError:
            company = self._universe_company(run_id, cid)
        self._ensure_run(s, run_id)
        stmt = insert(ReviewItem).values(
            run_id=run_id, item_key=row["item_key"], company_id=company,
            observation_id=observation_id or row.get("observation_id"), payload=row,
        )
        s.execute(
            stmt.on_conflict_do_update(
                constraint="uq_review_items_key",
                set_={
                    "payload": stmt.excluded.payload,
                    "company_id": stmt.excluded.company_id,
                    # a re-queue without a link (queue_for_review) keeps the one the item has
                    "observation_id": func.coalesce(stmt.excluded.observation_id, ReviewItem.observation_id),
                },
            )
        )

    def record_company_result(
        self,
        run_id: str,
        row: dict,
        *,
        observations: list[ObservationIn],
        review_items: list[tuple[str, dict]],
        company: CompanyRef | None,
        errors: list[dict] = (),
    ) -> None:
        """One company's result in one transaction (spec §3.1): the run_results row, `errors`
        (values left out of `observations`), the observations with their citations and fact
        updates, held documents, then the review items, each linked to the observation its
        payload names (field, period and basis). A `_key` already stored writes nothing."""
        row = _jsonb_safe(row)
        entity = company.entity_id if company is not None else None
        with self._tx(run_id) as s:
            if not self._insert_result(s, run_id, row, entity):
                return
            for e in errors:
                s.execute(insert(RunError).values(run_id=run_id, company_id=entity, error=_jsonb_safe(e)))
            ids = observations_db.record(s, observations)
            by_target = {
                (o.field_id, o.period_end.isoformat() if o.period_end else None, o.basis): i
                for o, i in zip(observations, ids, strict=True) if i is not None
            }
            if entity is not None:
                held = {d["doc_id"]: d.get("reason") for d in row.get("held_documents") or [] if d.get("doc_id")}
                known = set(s.scalars(select(Document.doc_id).where(Document.doc_id.in_(held)))) if held else set()
                for doc_id in known:
                    s.execute(insert(RunHeldDocument).values(
                        run_id=run_id, company_id=entity, doc_id=doc_id, reason=held[doc_id],
                    ).on_conflict_do_nothing())
            for key, payload in review_items:
                item = {"item_key": key, "queued_at": now_iso(), **_jsonb_safe(payload)}
                if company is not None:
                    item.setdefault("company_id", company.company_id)
                target = review_target(item)
                same = company is not None and item.get("company_id") == company.company_id
                self._insert_review_item(s, run_id, item, by_target.get(target) if target else None, entity if same else None)

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
            if decision is not None:
                self._apply_review(s, run_id, row.get("item_key"))

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
            self._apply_review(s, run_id, row.get("item_key"))

    @staticmethod
    def _apply_review(s: Session, run_id: str, item_key: str | None) -> None:
        """Once the item's decision is final (its cosign or second review done, where the run type
        needs one), the facts behind it take it (observations.apply_decision decides which).
        Until then they stay as they are."""
        from arp.orchestration.review_queue import FINAL_STATES, item_state
        from arp.review.items import cosign_rule  # imports the extraction pipeline

        item = s.scalar(select(ReviewItem).where(ReviewItem.run_id == run_id, ReviewItem.item_key == item_key))
        if item is None:
            return
        rows = s.execute(
            select(ReviewDecision.id, ReviewDecision.row).where(ReviewDecision.review_item_id == item.id).order_by(ReviewDecision.id)
        ).all()
        signed = set(s.scalars(
            select(ReviewCosign.row["decision_decided_at"].astext).where(ReviewCosign.review_item_id == item.id)
        ))
        run_type = s.scalar(select(Run.run_type).where(Run.run_id == run_id))
        state = item_state([r for _, r in rows], cosigned_at=signed, cosign_required=cosign_rule(run_type))
        if state.state not in FINAL_STATES:
            return
        eff = state.effective
        decision_id = next(i for i, r in rows if r is eff)
        edited = eff.get("corrected_value") or eff.get("edited_value")
        observations_db.apply_decision(s, item.id, DecisionKind(eff["decision"]), edited, decision_id)

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
