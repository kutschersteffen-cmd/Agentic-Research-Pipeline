from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from sqlalchemy.exc import OperationalError

from arp.db.to_observations import to_observations
from arp.llm.base import LLMUsage
from arp.orchestration.job_manager import JobManager
from arp.orchestration.jobs import hold_run
from arp.orchestration.review_queue import queue_for_review
from arp.orchestration.step_tally import on_company, tally_run
from arp.schemas.common import CompanyRef
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)

ItemT = TypeVar("ItemT")
ResultT = TypeVar("ResultT")

_KEY_FIELD = "_key"
_WRITE_RETRIES = 3
_RETRY_BACKOFF_S = 0.5


class ReviewRequired(Exception):
    """A worker stopping an item on purpose so a person looks at it: the
    item is not a result, and `report` (what went wrong, and what was known
    up to then) goes to the errors file and, in a company batch, to the
    run's review queue."""

    def __init__(self, message: str, report: dict) -> None:
        super().__init__(message)
        self.report = report


@dataclass(frozen=True)
class BatchSinks:
    """Where a batch reads its already-done keys from and writes result and
    error rows to. `run_sinks` points them at a run's own rows; a batch
    with a side file (emerging themes' extracted tags) builds its own."""

    done: Callable[[], set[str]]
    append_result: Callable[[dict], None]
    append_error: Callable[[dict], None]


def run_sinks(run_store: RunStore, run_id: str) -> BatchSinks:
    return BatchSinks(
        done=lambda: run_store.done_keys(run_id, include_errors=True),
        append_result=lambda row: run_store.append_result(run_id, row),
        append_error=lambda row: run_store.append_error(run_id, row),
    )


async def run_batch(
    items: list[ItemT],
    *,
    item_key: Callable[[ItemT], str],
    worker: Callable[[ItemT], Awaitable[ResultT]],
    sinks: BatchSinks,
    concurrency: int,
    result_to_json: Callable[[ResultT], dict],
    on_success: Callable[[ItemT, ResultT], None] | None = None,
    on_error: Callable[[ItemT, Exception], None] | None = None,
    resume: bool = True,
    cancel_check: Callable[[], bool] | None = None,
    write_result: Callable[[ItemT, ResultT, dict], Awaitable[None]] | None = None,
) -> None:
    """Runs `worker` over `items` with bounded concurrency.

    Precision-at-scale controls implemented here:
    - **Checkpointing**: every successful result is appended to
      `sinks.append_result` immediately, so progress is never lost.
    - **Resumability**: item keys already present in the results are
      skipped on the next invocation, so a 4000-company run interrupted at
      item 3,000 picks back up without redoing the first 3,000.
    - **Failure isolation**: one item's exception is logged to
      `sinks.append_error` and does not cancel or affect any other item.
    - **Bounded concurrency**: an `asyncio.Semaphore` caps in-flight work
      to respect API rate limits and be a polite web citizen.
    - **Cooperative cancellation**: `cancel_check`, if supplied, is polled
      before each item that hasn't started yet; once it returns True, no
      further items are launched. Items already in flight still finish and
      checkpoint normally -- this is a soft stop (no work is lost or left
      half-written), not a hard kill.

    `write_result`, if supplied, writes each success's row instead of
    `sinks.append_result` (run_company_batch: one transaction per company).
    """
    already_done = sinks.done() if resume else set()

    sem = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()

    async def _run_one(item: ItemT) -> None:
        key = item_key(item)
        if key in already_done:
            return
        if cancel_check and cancel_check():
            return
        async with sem:
            try:
                result = await worker(item)
            except Exception as exc:  # noqa: BLE001 - isolate failures per item
                logger.exception("Batch item %s failed", key)
                row = {"key": key, "error": str(exc)}
                if isinstance(exc, ReviewRequired):
                    row.update(review=True, report=exc.report)
                async with write_lock:
                    sinks.append_error(row)
                if on_error:
                    on_error(item, exc)
                return
        record = result_to_json(result)
        record[_KEY_FIELD] = key
        if write_result is not None:
            await write_result(item, result, record)
        else:
            async with write_lock:
                sinks.append_result(record)
        if on_success:
            on_success(item, result)

    await asyncio.gather(*(_run_one(item) for item in items))


async def run_company_batch(
    run_id: str,
    companies: list[CompanyRef],
    *,
    run_store: RunStore,
    worker: Callable[[CompanyRef], Awaitable[ResultT]],
    result_to_json: Callable[[ResultT], dict],
    review_items: Callable[[CompanyRef, ResultT], list[tuple[str, dict]]] | None = None,
    cost_usd: Callable[[ResultT], float] | None = None,
    concurrency: int,
) -> None:
    """The per-company run every pipeline shares: `run_batch` over the
    universe, keyed by company_id, checkpointed into the run's results and
    errors files, cancellable via the manifest's cancel_requested flag.
    Each success queues `review_items(company, result)` for human sign-off
    and records completed/review/token/cost progress (tokens from
    `result.usage`, when the result has one); each failure records
    failed_delta, except a ReviewRequired stop, whose report is queued for
    review instead. When the batch is done, applies the run's attached
    Decision Studio framework (arp.decision.templates.score_run), then
    finishes the run.
    """
    job_manager = JobManager(run_store)
    # The run's stored companies when it has them: resolved (entity_id set), identity conflicts
    # left out (save_companies recorded them as run errors), the same set on a fresh run and a resume.
    if run_store.has_companies(run_id):
        companies = run_store.load_companies(run_id) or []

    manifest = run_store.load_manifest(run_id)
    run_type = manifest.run_type if manifest else ""
    trial = bool(manifest and manifest.params.get("trial"))

    def _commit(company: CompanyRef, result: ResultT, row: dict) -> None:
        """The result row, its observations and facts, and its review items, in one transaction
        (spec §3.1), retried with backoff while the database is unreachable (spec §5); then the
        progress. Runs in a worker thread, which finishes both even if the batch task is cancelled
        meanwhile, so a stored result always has its progress counted."""
        items = review_items(company, result) if review_items else []
        errors: list[dict] = []
        observations = (
            to_observations(run_type, company.entity_id, run_id, row, trial=trial, errors=errors)
            if company.entity_id is not None else []
        )
        for attempt in range(_WRITE_RETRIES + 1):
            try:
                run_store.record_company_result(
                    run_id, row, observations=observations, review_items=items, company=company, errors=errors,
                )
                break
            except OperationalError:
                if attempt == _WRITE_RETRIES:
                    raise
                logger.warning("Writing %s for run %s failed; retrying", company.company_id, run_id, exc_info=True)
                time.sleep(_RETRY_BACKOFF_S * 2**attempt)
        usage = getattr(result, "usage", None) or LLMUsage()
        job_manager.record_progress(
            run_id,
            completed_delta=1,
            review_delta=len(items),
            input_tokens_delta=usage.input_tokens,
            output_tokens_delta=usage.output_tokens,
            cost_delta_usd=cost_usd(result) if cost_usd else 0.0,
        )

    async def _write_result(company: CompanyRef, result: ResultT, row: dict) -> None:
        await asyncio.to_thread(_commit, company, result, row)

    def _on_error(company: CompanyRef, exc: Exception) -> None:
        if isinstance(exc, ReviewRequired):
            queue_for_review(run_store, run_id, company.company_id, exc.report, company=company)
            job_manager.record_progress(run_id, review_delta=1)
        else:
            job_manager.record_progress(run_id, failed_delta=1)

    async def _worker(company: CompanyRef) -> ResultT:
        with on_company(company.company_id):
            return await worker(company)

    def _cancel_check() -> bool:
        current = run_store.load_manifest(run_id)
        return current is not None and current.cancel_requested

    with hold_run(run_store, run_id):  # one worker per run; RunBusy if another holds it
        with tally_run(run_store, run_id):
            await run_batch(
                companies,
                item_key=lambda c: c.company_id,
                worker=_worker,
                sinks=run_sinks(run_store, run_id),
                concurrency=concurrency,
                result_to_json=result_to_json,
                on_error=_on_error,
                cancel_check=_cancel_check,
                write_result=_write_result,
            )
        # The rules step: a run with a Decision Studio framework attached is
        # scored before it is marked finished, so a finished run's scores are
        # already stored when anyone looks. A no-op without one. Whatever goes
        # wrong in it, the run still finishes: its extracted results stand.
        from arp.decision.templates import score_run

        try:
            score_run(run_store, run_id)
        except Exception:  # noqa: BLE001
            logger.exception("Rules step failed for run %s", run_id)
        job_manager.finish_run(run_id)
