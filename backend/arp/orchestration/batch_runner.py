from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable, TypeVar

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
