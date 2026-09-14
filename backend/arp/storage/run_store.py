from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from arp.schemas.common import JobStatus, RunManifest, now_iso
from arp.storage.locks import KeyedLock
from arp.storage.postgres_projection_config import ProjectionConfig
from arp.storage.safe_path import safe_id

# Statuses a run can end in with results worth syncing into the opt-in
# Postgres company-records/company-facts projections (see
# postgres_company_records_projection.py, postgres_company_facts_projection.py).
# CANCELLED is included too: a mid-batch cancel can still leave real rows
# in results.jsonl, and syncing an empty file is simply a no-op.
_TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.PARTIALLY_COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


class RunStore:
    """File-based persistence for a run's manifest, results, errors, and
    review state. No database: everything is a JSON/JSONL file under
    `runs/<run_id>/`, which keeps runs resumable, inspectable, and trivial
    to back up or ship elsewhere.
    """

    def __init__(self, runs_dir: Path, projection_config: ProjectionConfig | None = None) -> None:
        self.runs_dir = runs_dir
        self._locks = KeyedLock()
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

    def results_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "results.jsonl"

    def errors_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "errors.jsonl"

    def review_queue_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "review_queue.jsonl"

    def review_decisions_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "review_decisions.jsonl"

    def events_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "events.jsonl"

    def save_manifest(self, manifest: RunManifest) -> None:
        manifest.updated_at = now_iso()
        path = self.manifest_path(manifest.run_id)
        # Write-then-rename is atomic on POSIX: a concurrent reader either
        # sees the old manifest or the new one in full, never a
        # half-written file from a write that's still in progress.
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".manifest_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(manifest.model_dump_json(indent=2))
            os.replace(tmp_path, path)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise

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
        return RunManifest.model_validate_json(path.read_text())

    def list_runs(self, run_type: str | None = None) -> list[RunManifest]:
        manifests: list[RunManifest] = []
        if not self.runs_dir.exists():
            return manifests
        for d in sorted(self.runs_dir.iterdir(), reverse=True):
            mp = d / "manifest.json"
            if not mp.exists():
                continue
            try:
                m = RunManifest.model_validate_json(mp.read_text())
            except (json.JSONDecodeError, OSError, ValueError):
                continue
            if run_type and m.run_type != run_type:
                continue
            manifests.append(m)
        return manifests

    @staticmethod
    def read_jsonl(path: Path) -> list[dict]:
        if not path.exists():
            return []
        rows = []
        with path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return rows

    @staticmethod
    def append_jsonl(path: Path, row: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(row) + "\n")
