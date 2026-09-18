from __future__ import annotations

import logging

from arp.config import Settings
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import queue_for_review
from arp.schemas.transition_barrier import BarrierRefreshFinding
from arp.storage.jsonl_io import append_jsonl
from arp.storage.run_store import RunStore
from arp.transition_barrier.dataset import filter_scores
from arp.transition_barrier.refresh.eurlex import build_client, fetch_version
from arp.transition_barrier.refresh.reconciler import is_auto_applicable, reconcile
from arp.transition_barrier.refresh.router import RoutedSource, automatable_sources, coverage_summary

logger = logging.getLogger(__name__)

RUN_TYPE = "transition_barrier_refresh"


class RefreshDisabledError(RuntimeError):
    """Raised when a refresh is requested while the feature is switched off."""


def create_refresh_run(settings: Settings, run_store: RunStore) -> str:
    """Create the run manifest. Counts sources, not companies -- the unit of
    work here is one legal act, not one issuer.
    """
    if not settings.transition_barrier_refresh_enabled:
        raise RefreshDisabledError(
            "Transition barrier refresh is disabled. Set ARP_TRANSITION_BARRIER_REFRESH_ENABLED=true to enable it."
        )
    sources = automatable_sources()
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run(RUN_TYPE, coverage_summary(), len(sources))
    return manifest.run_id


async def execute_refresh_run(run_id: str, *, settings: Settings, run_store: RunStore) -> list[BarrierRefreshFinding]:
    """Re-check every automatable source and record what it implies.

    Findings that need a human (rating-change candidates, conflicts, fetch
    failures) go to the review queue. Nothing here writes to
    assessment_scores.json -- see `is_auto_applicable` for the one rule that
    decides what could ever be written back, and note that even an
    auto-applicable finding only licenses refreshing evidence text and
    last_verified, never the H/M/L rating.
    """
    if not settings.transition_barrier_refresh_enabled:
        raise RefreshDisabledError("Transition barrier refresh is disabled.")

    job_manager = JobManager(run_store)
    routed: list[RoutedSource] = automatable_sources()
    findings: list[BarrierRefreshFinding] = []

    async with build_client() as client:
        for source in routed:
            fetched = await fetch_version(source, client=client)
            source_findings = [
                reconcile(score, fetched, recorded_point_in_time=score.last_verified)
                for code in source.source.used_by_criteria
                for region in source.regions
                for score in filter_scores(code=code, region=region)
            ]

            needs_review = 0
            for finding in source_findings:
                append_jsonl(run_store.results_path(run_id), finding.model_dump(mode="json"))
                if not is_auto_applicable(finding):
                    queue_for_review(
                        run_store,
                        run_id,
                        f"{finding.code}:{finding.region.value}:{finding.source_key}",
                        finding.model_dump(mode="json"),
                    )
                    needs_review += 1

            findings.extend(source_findings)
            # completed and failed are mutually exclusive, matching how every
            # other pipeline here reports progress (see run_batch's
            # on_success/on_error split) -- otherwise a failed source shows up
            # in both counters and the run looks twice its real size.
            job_manager.record_progress(
                run_id,
                completed_delta=0 if fetched.failed else 1,
                failed_delta=1 if fetched.failed else 0,
                review_delta=needs_review,
            )

    job_manager.finish_run(run_id)
    return findings


async def run_refresh(*, settings: Settings, run_store: RunStore) -> tuple[str, list[BarrierRefreshFinding]]:
    """Create + execute in one call, for the CLI where blocking is expected."""
    run_id = create_refresh_run(settings, run_store)
    return run_id, await execute_refresh_run(run_id, settings=settings, run_store=run_store)
