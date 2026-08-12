from __future__ import annotations

from arp.schemas.common import JobStatus, RunManifest, new_id
from arp.storage.run_store import RunStore


class JobManager:
    """Owns run lifecycle: creation, progress updates, completion.

    Thin wrapper over RunStore so pipelines don't hand-roll manifest
    bookkeeping; all state changes go through here and are immediately
    flushed to disk, so the API/CLI/UI can always read live progress.
    """

    def __init__(self, store: RunStore) -> None:
        self.store = store

    def create_run(self, run_type: str, params: dict, company_count: int, model: str | None = None) -> RunManifest:
        manifest = RunManifest(
            run_id=new_id(run_type),
            run_type=run_type,
            status=JobStatus.RUNNING,
            params=params,
            company_count=company_count,
            model=model,
        )
        self.store.save_manifest(manifest)
        return manifest

    def record_progress(
        self,
        run_id: str,
        *,
        completed_delta: int = 0,
        failed_delta: int = 0,
        review_delta: int = 0,
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
        cost_delta_usd: float = 0.0,
    ) -> RunManifest:
        manifest = self.store.load_manifest(run_id)
        if manifest is None:
            raise ValueError(f"Unknown run_id: {run_id}")
        manifest.completed_count += completed_delta
        manifest.failed_count += failed_delta
        manifest.review_count += review_delta
        manifest.input_tokens += input_tokens_delta
        manifest.output_tokens += output_tokens_delta
        manifest.estimated_cost_usd += cost_delta_usd
        self.store.save_manifest(manifest)
        return manifest

    def finish_run(self, run_id: str, error: str | None = None) -> RunManifest:
        manifest = self.store.load_manifest(run_id)
        if manifest is None:
            raise ValueError(f"Unknown run_id: {run_id}")
        if error:
            manifest.status = JobStatus.FAILED
            manifest.error = error
        elif manifest.failed_count > 0:
            manifest.status = JobStatus.PARTIALLY_COMPLETED
        else:
            manifest.status = JobStatus.COMPLETED
        self.store.save_manifest(manifest)
        return manifest
