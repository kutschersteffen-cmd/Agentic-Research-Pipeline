from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

try:  # POSIX only; see KeyedLock's docstring for what is lost without it.
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None


class KeyedLock:
    """A registry of per-key locks, so a caller can serialize a
    read-modify-write cycle against one key (a run_id, a company_id, a
    registry file) without blocking unrelated keys.

    **Within a process** this is a reentrant thread lock. Route handlers in
    this app are declared as sync `def`s, which FastAPI dispatches to real
    OS worker threads -- so a request handled on a worker thread genuinely
    races the event-loop thread running a batch's own progress updates.
    Without a lock like this, two concurrent mutations of the same
    file-backed record (e.g. a cancel request and an in-flight batch's
    progress write) can interleave their read-modify-write cycles and
    silently lose one side's update. RLock (not Lock) so a mutator that
    calls another mutator on the same key from the same thread doesn't
    deadlock against itself.

    **Across processes**, pass `lock_path` -- a callable mapping a key to a
    sidecar lock file -- and each acquisition also takes an advisory
    `flock` on that file. A thread lock cannot help there, and this app
    genuinely has concurrent processes writing the same files: `arp ...`
    CLI commands operate on the same `runs/`, `portfolios/`,
    `engagements/` and `taxonomies/` directories as a running API, and
    `uvicorn --workers N` would put several API processes on them too. The
    lock file is created next to the data it guards, holds no content, and
    is never deleted (unlinking it would let two processes end up holding
    flocks on two different inodes for the same key).

    `flock` is advisory and per-fd: a process that doesn't take it is not
    blocked, and it releases automatically if a holder crashes, so a stale
    lock file never wedges the system. Where `fcntl` is unavailable
    (Windows), the cross-process half degrades to a no-op and the
    thread-level guarantee still holds -- the deployment targets here
    (Docker, uvicorn on Linux/macOS) all have it.
    """

    def __init__(self, lock_path: Callable[[str], Path] | None = None) -> None:
        self._locks: dict[str, threading.RLock] = {}
        self._registry_lock = threading.Lock()
        self._lock_path = lock_path
        # key -> (open file object, reentrancy depth). Only ever touched
        # while this key's RLock is held, so it needs no lock of its own.
        self._files: dict[str, tuple[object, int]] = {}

    def _get(self, key: str) -> threading.RLock:
        with self._registry_lock:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._locks[key] = lock
            return lock

    def _acquire_file_lock(self, key: str) -> None:
        if self._lock_path is None or fcntl is None:
            return
        entry = self._files.get(key)
        if entry is not None:  # already held by this thread: just go deeper
            handle, depth = entry
            self._files[key] = (handle, depth + 1)
            return
        path = self._lock_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except BaseException:
            handle.close()
            raise
        self._files[key] = (handle, 1)

    def _release_file_lock(self, key: str) -> None:
        entry = self._files.get(key)
        if entry is None:
            return
        handle, depth = entry
        if depth > 1:
            self._files[key] = (handle, depth - 1)
            return
        del self._files[key]
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()  # closing would release it anyway; explicit for clarity

    @contextmanager
    def acquire(self, key: str) -> Iterator[None]:
        with self._get(key):
            self._acquire_file_lock(key)
            try:
                yield
            finally:
                self._release_file_lock(key)
