import threading
import time
from unittest.mock import patch

from arp.orchestration.job_manager import JobManager
from arp.storage.locks import KeyedLock
from arp.storage.run_store import RunStore


def test_keyed_lock_serializes_same_key():
    lock = KeyedLock()
    events: list[tuple[str, str, float]] = []

    def worker(name: str, hold_seconds: float) -> None:
        with lock.acquire("shared"):
            events.append(("enter", name, time.monotonic()))
            time.sleep(hold_seconds)
            events.append(("exit", name, time.monotonic()))

    t1 = threading.Thread(target=worker, args=("a", 0.05))
    t2 = threading.Thread(target=worker, args=("b", 0.0))
    t1.start()
    time.sleep(0.01)  # make sure t1 acquires first
    t2.start()
    t1.join()
    t2.join()

    a_exit = next(t for kind, name, t in events if kind == "exit" and name == "a")
    b_enter = next(t for kind, name, t in events if kind == "enter" and name == "b")
    assert b_enter >= a_exit, "second thread entered the critical section before the first exited"


def test_keyed_lock_does_not_serialize_different_keys():
    lock = KeyedLock()
    started = threading.Event()
    finished = threading.Event()

    def hold_a():
        with lock.acquire("a"):
            started.set()
            time.sleep(0.1)

    t = threading.Thread(target=hold_a)
    t.start()
    started.wait(timeout=1)
    # A different key must not block behind "a"'s lock.
    acquired_quickly = False
    start = time.monotonic()
    with lock.acquire("b"):
        acquired_quickly = (time.monotonic() - start) < 0.05
    finished.set()
    t.join()
    assert acquired_quickly


def test_record_progress_has_no_lost_updates_under_concurrency(tmp_path):
    # Widen the read-modify-write window (simulating real disk I/O latency)
    # so that without RunStore.lock(), concurrent record_progress calls
    # would deterministically clobber each other's deltas.
    store = RunStore(tmp_path / "runs")
    manager = JobManager(store)
    manifest = manager.create_run("theme", {}, company_count=100)

    original_load = RunStore.load_manifest

    def slow_load(self, run_id):
        result = original_load(self, run_id)
        time.sleep(0.005)
        return result

    n_threads = 20
    with patch.object(RunStore, "load_manifest", slow_load):
        threads = [threading.Thread(target=lambda: manager.record_progress(manifest.run_id, completed_delta=1)) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    final = store.load_manifest(manifest.run_id)
    assert final.completed_count == n_threads
