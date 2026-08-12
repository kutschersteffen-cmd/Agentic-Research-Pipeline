from __future__ import annotations

import json
from pathlib import Path

from arp.schemas.common import RunManifest, now_iso


class RunStore:
    """File-based persistence for a run's manifest, results, errors, and
    review state. No database: everything is a JSON/JSONL file under
    `runs/<run_id>/`, which keeps runs resumable, inspectable, and trivial
    to back up or ship elsewhere.
    """

    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir

    def run_dir(self, run_id: str) -> Path:
        d = self.runs_dir / run_id
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
        self.manifest_path(manifest.run_id).write_text(manifest.model_dump_json(indent=2))

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
