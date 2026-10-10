from __future__ import annotations

from collections.abc import Callable

from arp.schemas.common import CompanyRef, JobStatus, RunManifest, new_id
from arp.storage.run_store import RunStore


class JobManager:
    """Owns run lifecycle: creation, progress updates, completion.

    Thin wrapper over RunStore so pipelines don't hand-roll manifest
    bookkeeping; all state changes go through here and are immediately
    flushed to disk, so the API/CLI/UI can always read live progress.
    """

    def __init__(self, store: RunStore) -> None:
        self.store = store

    def create_run(
        self,
        run_type: str,
        params: dict,
        company_count: int,
        model: str | None = None,
        verifier_model: str | None = None,
        companies: list[CompanyRef] | None = None,
    ) -> RunManifest:
        manifest = RunManifest(
            run_id=new_id(run_type),
            run_type=run_type,
            status=JobStatus.RUNNING,
            params=params,
            company_count=company_count,
            model=model,
            verifier_model=verifier_model,
        )
        self.store.save_manifest(manifest)
        if companies is not None:
            # What a resume re-runs over: see RunStore.load_companies.
            self.store.save_companies(manifest.run_id, companies)
        return manifest

    def _update(self, run_id: str, fn: Callable[[RunManifest], None]) -> RunManifest:
        # Locked because a batch's own progress writes (from the event-loop
        # thread) and a sync API route like /cancel (dispatched to a real
        # worker thread by FastAPI) both read-modify-write the same
        # manifest.json -- without this, whichever write lands second wins
        # outright and silently discards the other side's update.
        with self.store.lock(run_id):
            manifest = self.store.load_manifest(run_id)
            if manifest is None:
                raise ValueError(f"Unknown run_id: {run_id}")
            fn(manifest)
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
        def fn(manifest: RunManifest) -> None:
            manifest.completed_count += completed_delta
            manifest.failed_count += failed_delta
            manifest.review_count += review_delta
            manifest.input_tokens += input_tokens_delta
            manifest.output_tokens += output_tokens_delta
            manifest.estimated_cost_usd += cost_delta_usd

        return self._update(run_id, fn)

    def finish_run(self, run_id: str, error: str | None = None) -> RunManifest:
        def fn(manifest: RunManifest) -> None:
            if error:
                manifest.status = JobStatus.FAILED
                manifest.error = error
            elif manifest.cancel_requested and manifest.completed_count + manifest.failed_count < manifest.company_count:
                # Cancelled before every item was processed -- distinct from a
                # legitimate partial failure, so the UI/CLI can tell "the user
                # stopped this" apart from "some items errored out".
                manifest.status = JobStatus.CANCELLED
            elif manifest.failed_count > 0:
                manifest.status = JobStatus.PARTIALLY_COMPLETED
            else:
                manifest.status = JobStatus.COMPLETED

        return self._update(run_id, fn)

    def mark_running(self, run_id: str) -> RunManifest:
        """A (re)start: running again, with the last attempt's error and cancel request cleared."""

        def fn(manifest: RunManifest) -> None:
            manifest.status = JobStatus.RUNNING
            manifest.error = None
            manifest.cancel_requested = False

        return self._update(run_id, fn)

    def request_cancel(self, run_id: str) -> RunManifest:
        return self._update(run_id, lambda m: setattr(m, "cancel_requested", True))
