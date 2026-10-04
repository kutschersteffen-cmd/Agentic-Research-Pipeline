from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Protocol

from arp.storage.run_store import RunStore

try:  # POSIX only; same guard as KeyedLock. Without it a lease never conflicts.
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

logger = logging.getLogger(__name__)


class RunBusy(RuntimeError):
    """Another worker already holds this run's lease."""


@contextmanager
def run_lease(run_store: RunStore, run_id: str) -> Iterator[None]:
    """One worker per run: a non-blocking exclusive `flock` on
    `runs/<id>/.worker`. Raises RunBusy if it is held -- by a thread or
    process, through any RunStore. The OS frees it if the holder dies, so
    a crashed worker never leaves a run stuck; the file itself is kept."""
    if fcntl is None:  # pragma: no cover - Windows
        yield
        return
    with (run_store.run_dir(run_id) / ".worker").open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RunBusy(f"Run {run_id} already has a worker") from None
        yield  # closing the handle releases the lock


class JobLauncher(Protocol):
    def launch(self, run_id: str, job: Callable[[], Awaitable[None]]) -> None: ...


class LocalJobLauncher:
    """Runs a run's job as a background task in this process, under the
    run's lease. `run_store` is a factory so the app's current settings
    decide where `runs/` is at launch time."""

    def __init__(self, run_store: Callable[[], RunStore]) -> None:
        self._run_store = run_store
        self._tasks: set[asyncio.Task] = set()  # strong refs: a running task is never garbage-collected

    def launch(self, run_id: str, job: Callable[[], Awaitable[None]]) -> None:
        async def _leased() -> None:
            try:
                with run_lease(self._run_store(), run_id):
                    await job()
            except Exception:  # noqa: BLE001 - nobody awaits the task
                logger.exception("Job for run %s failed", run_id)

        task = asyncio.create_task(_leased())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


_launcher: JobLauncher | None = None


def get_job_launcher() -> JobLauncher:
    global _launcher
    if _launcher is None:
        from arp.api.deps import get_run_store

        # ponytail: a cloud_run launcher plugs in here at Cloud switch-on.
        _launcher = LocalJobLauncher(get_run_store)
    return _launcher
