from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from arp.schemas.common import CompanyRef, JobStatus, RunManifest, now_iso
from arp.storage.atomic_io import atomic_write_text, read_text_utf8
from arp.storage.jsonl_io import append_jsonl, read_jsonl
from arp.storage.locks import KeyedLock
from arp.storage.postgres_projection_config import ProjectionConfig
from arp.storage.safe_path import safe_id

# Statuses a run can end in with results worth syncing into the opt-in
# Postgres company-records/company-facts projections (see
# postgres_company_records_projection.py, postgres_company_facts_projection.py).
# CANCELLED is included too: a mid-batch cancel can still leave real rows
# in results.jsonl, and syncing an empty file is simply a no-op.
_TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.PARTIALLY_COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


def done_keys_from_rows(result_rows: Iterable[dict], error_rows: Iterable[dict] = ()) -> set[str]:
    """Keys of items not to run again: every result row's `_key`, plus every
    error row a worker stopped for review (`review` set) -- a person decides
    those, so a resume must not redo them."""
    done = {row["_key"] for row in result_rows if row.get("_key")}
    done.update(row["key"] for row in error_rows if row.get("review") and row.get("key"))
    return done


class RunStore:
    """File-based persistence for a run's manifest, results, errors, and
    review state. No database: everything is a JSON/JSONL file under
    `runs/<run_id>/`, which keeps runs resumable, inspectable, and trivial
    to back up or ship elsewhere.
    """

    def __init__(self, runs_dir: Path, projection_config: ProjectionConfig | None = None) -> None:
        self.runs_dir = runs_dir
        # Cross-process too, not just cross-thread: `arp runs ...` CLI
        # commands and the scheduler write the same runs/ directory as a
        # live API process. See KeyedLock.
        self._locks = KeyedLock(lock_path=lambda run_id: self.run_dir(run_id) / ".lock")
        self._projection_config = projection_config

    @contextmanager
    def lock(self, run_id: str) -> Iterator[None]:
        """Serializes a read-modify-write cycle against one run's manifest
        -- see JobManager, whose record_progress/finish_run/request_cancel
        each wrap their whole read-then-save in this."""
        with self._locks.acquire(run_id):
            yield

    def run_dir(self, run_id: str) -> Path:
        d = self.runs_dir / safe_id(run_id, label="run_id")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def manifest_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "manifest.json"

    def _results_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "results.jsonl"

    def _errors_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "errors.jsonl"

    def _companies_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "companies.json"

    def _review_queue_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "review_queue.jsonl"

    def _review_decisions_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "review_decisions.jsonl"

    def _review_cosigns_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "review_cosigns.jsonl"

    def _restatements_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "restatement_candidates.jsonl"

    def _snapshot_path(self, run_id: str, snapshot_id: str) -> Path:
        return self.run_dir(run_id) / "snapshots" / f"{safe_id(snapshot_id, label='snapshot_id')}.json"

    def _events_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "events.jsonl"

    # Row access. Callers never see a path, so the backing store can change
    # without touching them.
    def read_results(self, run_id: str) -> list[dict]:
        return read_jsonl(self._results_path(run_id))

    def append_result(self, run_id: str, row: dict) -> None:
        append_jsonl(self._results_path(run_id), row)

    def read_errors(self, run_id: str) -> list[dict]:
        return read_jsonl(self._errors_path(run_id))

    def append_error(self, run_id: str, row: dict) -> None:
        append_jsonl(self._errors_path(run_id), row)

    def read_review_queue(self, run_id: str) -> list[dict]:
        return read_jsonl(self._review_queue_path(run_id))

    def append_review_item(self, run_id: str, row: dict) -> None:
        append_jsonl(self._review_queue_path(run_id), row)

    def read_decisions(self, run_id: str) -> list[dict]:
        return read_jsonl(self._review_decisions_path(run_id))

    def append_decision_row(self, run_id: str, row: dict) -> None:
        append_jsonl(self._review_decisions_path(run_id), row)

    def read_cosigns(self, run_id: str) -> list[dict]:
        return read_jsonl(self._review_cosigns_path(run_id))

    def append_cosign(self, run_id: str, row: dict) -> None:
        append_jsonl(self._review_cosigns_path(run_id), row)

    def read_restatements(self, run_id: str) -> list[dict]:
        return read_jsonl(self._restatements_path(run_id))

    def append_restatement(self, run_id: str, row: dict) -> None:
        append_jsonl(self._restatements_path(run_id), row)

    def read_events(self, run_id: str) -> list[dict]:
        return read_jsonl(self._events_path(run_id))

    def append_event(self, run_id: str, row: dict) -> None:
        append_jsonl(self._events_path(run_id), row)

    def read_snapshot(self, run_id: str, snapshot_id: str) -> dict | None:
        path = self._snapshot_path(run_id, snapshot_id)
        return json.loads(read_text_utf8(path)) if path.exists() else None

    def save_snapshot(self, run_id: str, snapshot_id: str, data: dict) -> None:
        path = self._snapshot_path(run_id, snapshot_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(data, sort_keys=True))

    def done_keys(self, run_id: str, *, include_errors: bool = False) -> set[str]:
        return done_keys_from_rows(self.read_results(run_id), self.read_errors(run_id) if include_errors else ())

    def save_manifest(self, manifest: RunManifest) -> None:
        manifest.updated_at = now_iso()
        # Write-then-rename (see arp/storage/atomic_io.py): a concurrent
        # reader either sees the old manifest or the new one in full,
        # never a half-written file from a write still in progress.
        atomic_write_text(self.manifest_path(manifest.run_id), manifest.model_dump_json(indent=2), prefix=".manifest_")

        if self._projection_config is not None and manifest.status in _TERMINAL_STATUSES:
            self._sync_projections(manifest.run_id)

    def _sync_projections(self, run_id: str) -> None:
        """Best-effort opt-in Postgres sync, fired once a run's manifest
        lands on a terminal status -- see postgres_company_records_
        projection.py/postgres_company_facts_projection.py for the
        unconditional work and their own exception-swallowing contract.
        A no-op whenever neither projection is enabled."""
        config = self._projection_config
        if config.company_records_enabled:
            from arp.storage.postgres_company_records_projection import sync_run_if_enabled

            sync_run_if_enabled(config, self, run_id)
        if config.company_facts_enabled:
            from arp.storage.postgres_company_facts_projection import materialize_run_if_enabled

            materialize_run_if_enabled(config, self, run_id)

    def load_manifest(self, run_id: str) -> RunManifest | None:
        path = self.manifest_path(run_id)
        if not path.exists():
            return None
        return RunManifest.model_validate_json(read_text_utf8(path))

    def load_companies(self, run_id: str) -> list[CompanyRef] | None:
        """The companies a run was created over, or None for a run that
        stored none (voting, older runs) and so cannot be resumed."""
        path = self._companies_path(run_id)
        if not path.exists():
            return None
        return [CompanyRef.model_validate(c) for c in json.loads(read_text_utf8(path))]

    def save_companies(self, run_id: str, companies: list[CompanyRef]) -> None:
        atomic_write_text(
            self._companies_path(run_id),
            json.dumps([c.model_dump(mode="json") for c in companies], indent=2),
            prefix=".companies_",
        )

    def has_companies(self, run_id: str) -> bool:
        return self._companies_path(run_id).exists()

    def list_runs(self, run_type: str | None = None) -> list[RunManifest]:
        """Newest first by created_at -- run_ids are a random uuid fragment
        (see arp.schemas.common.new_id), so directory order means nothing."""
        manifests: list[RunManifest] = []
        if not self.runs_dir.exists():
            return manifests
        for d in self.runs_dir.iterdir():
            mp = d / "manifest.json"
            if not mp.exists():
                continue
            try:
                m = RunManifest.model_validate_json(read_text_utf8(mp))
            except (OSError, ValueError):  # ValueError covers pydantic's own JSON errors
                continue
            if run_type and m.run_type != run_type:
                continue
            manifests.append(m)
        return sorted(manifests, key=lambda m: m.created_at, reverse=True)

    def extraction_runs(self) -> list[RunManifest]:
        """Non-trial extraction runs, newest first."""
        return [m for m in self.list_runs("extraction") if not m.params.get("trial")]

    # Kept as staticmethods on the store (rather than callers importing
    # jsonl_io directly) because every existing call site -- pipelines,
    # review_queue, the projections -- already goes through RunStore.
    read_jsonl = staticmethod(read_jsonl)
    append_jsonl = staticmethod(append_jsonl)
