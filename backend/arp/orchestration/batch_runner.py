from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol, TypeVar

from arp.llm.base import LLMUsage
from arp.orchestration.job_manager import JobManager
from arp.orchestration.review_queue import queue_for_review
from arp.schemas.common import CompanyRef
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)

ItemT = TypeVar("ItemT")
ResultT = TypeVar("ResultT")

_KEY_FIELD = "_key"


def read_done_keys(results_path: Path) -> set[str]:
    if not results_path.exists():
        return set()
    import json

    done: set[str] = set()
    with results_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = row.get(_KEY_FIELD)
            if key:
                done.add(key)
    return done


async def run_batch(
    items: list[ItemT],
    *,
    item_key: Callable[[ItemT], str],
    worker: Callable[[ItemT], Awaitable[ResultT]],
    results_path: Path,
    errors_path: Path,
    concurrency: int,
    result_to_json: Callable[[ResultT], dict],
    on_success: Callable[[ItemT, ResultT], None] | None = None,
    on_error: Callable[[ItemT, Exception], None] | None = None,
    resume: bool = True,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    """Runs `worker` over `items` with bounded concurrency.

    Precision-at-scale controls implemented here:
    - **Checkpointing**: every successful result is appended to
      `results_path` (JSONL) immediately, so progress is never lost.
    - **Resumability**: item keys already present in `results_path` are
      skipped on the next invocation, so a 4000-company run interrupted at
      item 3,000 picks back up without redoing the first 3,000.
    - **Failure isolation**: one item's exception is logged to
      `errors_path` and does not cancel or affect any other item.
    - **Bounded concurrency**: an `asyncio.Semaphore` caps in-flight work
      to respect API rate limits and be a polite web citizen.
    - **Cooperative cancellation**: `cancel_check`, if supplied, is polled
      before each item that hasn't started yet; once it returns True, no
      further items are launched. Items already in flight still finish and
      checkpoint normally -- this is a soft stop (no work is lost or left
      half-written), not a hard kill.
    """
    import json

    results_path.parent.mkdir(parents=True, exist_ok=True)
    errors_path.parent.mkdir(parents=True, exist_ok=True)
    already_done = read_done_keys(results_path) if resume else set()

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
                async with write_lock:
                    with errors_path.open("a") as f:
                        f.write(json.dumps({"key": key, "error": str(exc)}) + "\n")
                if on_error:
                    on_error(item, exc)
                return
        record = result_to_json(result)
        record[_KEY_FIELD] = key
        async with write_lock:
            with results_path.open("a") as f:
                f.write(json.dumps(record) + "\n")
        if on_success:
            on_success(item, result)

    await asyncio.gather(*(_run_one(item) for item in items))


class _HasUsage(Protocol):
    usage: LLMUsage


UsageResultT = TypeVar("UsageResultT", bound=_HasUsage)


async def run_company_batch(
    run_id: str,
    companies: list[CompanyRef],
    *,
    run_store: RunStore,
    worker: Callable[[CompanyRef], Awaitable[UsageResultT]],
    result_to_json: Callable[[UsageResultT], dict],
    review_items: Callable[[CompanyRef, UsageResultT], list[tuple[str, dict]]],
    cost_usd: Callable[[UsageResultT], float],
    concurrency: int,
) -> None:
    """The per-company LLM run every pipeline shares: `run_batch` over the
    universe, keyed by company_id, checkpointed into the run's results and
    errors files, cancellable via the manifest's cancel_requested flag.
    Each success queues `review_items(company, result)` for human sign-off
    and records completed/review/token/cost progress; each failure records
    failed_delta. Finishes the run when the batch is done.
    """
    job_manager = JobManager(run_store)

    def _on_success(company: CompanyRef, result: UsageResultT) -> None:
        items = review_items(company, result)
        for key, payload in items:
            queue_for_review(run_store, run_id, key, payload)
        job_manager.record_progress(
            run_id,
            completed_delta=1,
            review_delta=len(items),
            input_tokens_delta=result.usage.input_tokens,
            output_tokens_delta=result.usage.output_tokens,
            cost_delta_usd=cost_usd(result),
        )

    def _cancel_check() -> bool:
        current = run_store.load_manifest(run_id)
        return current is not None and current.cancel_requested

    await run_batch(
        companies,
        item_key=lambda c: c.company_id,
        worker=worker,
        results_path=run_store.results_path(run_id),
        errors_path=run_store.errors_path(run_id),
        concurrency=concurrency,
        result_to_json=result_to_json,
        on_success=_on_success,
        on_error=lambda company, exc: job_manager.record_progress(run_id, failed_delta=1),
        cancel_check=_cancel_check,
    )
    job_manager.finish_run(run_id)
