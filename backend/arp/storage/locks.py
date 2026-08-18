from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator


class KeyedLock:
    """A registry of per-key reentrant locks, so a caller can serialize a
    read-modify-write cycle against one key (a run_id, a company_id)
    without blocking unrelated keys.

    Route handlers in this app are declared as sync `def`s, which FastAPI
    dispatches to real OS worker threads -- so a request handled on a
    worker thread genuinely races the event-loop thread running a batch's
    own progress updates. Without a lock like this, two concurrent
    mutations of the same file-backed record (e.g. a cancel request and an
    in-flight batch's progress write) can interleave their read-modify-
    write cycles and silently lose one side's update. RLock (not Lock) so
    a mutator that calls another mutator on the same key from the same
    thread doesn't deadlock against itself.
    """

    def __init__(self) -> None:
        self._locks: dict[str, threading.RLock] = {}
        self._registry_lock = threading.Lock()

    def _get(self, key: str) -> threading.RLock:
        with self._registry_lock:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._locks[key] = lock
            return lock

    @contextmanager
    def acquire(self, key: str) -> Iterator[None]:
        lock = self._get(key)
        with lock:
            yield
