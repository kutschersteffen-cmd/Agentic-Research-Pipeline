"""Concurrency regressions for the two file stores that previously had
neither a lock nor an atomic write: PortfolioStore's registry files and
TaxonomyStore's version files.

Both stores are reached from sync FastAPI route handlers, which run on
real worker threads (and, for PortfolioStore, through an lru_cached
singleton shared by all of them), so the threads below are what those
routes actually do under concurrent requests -- not a synthetic stress
test. The same pattern as tests/test_run_store_locking.py, which covers
RunStore/EngagementStore.

Before the fix, 50 concurrent save_security calls kept 15-19 of 50 and
most threads died reading a file that had been truncated mid-write; 8
concurrent new_version calls produced one v2 that 7 of them overwrote in
turn.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import ThemeDefinition
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.taxonomy_store import TaxonomyStore

WRITERS = 50


def _run_in_threads(target, count: int) -> list[BaseException]:
    """Runs `target(i)` on `count` threads, collecting any exception each
    raised -- a thread that dies would otherwise just print a traceback
    and leave the test passing."""
    errors: list[BaseException] = []

    def wrapped(i: int) -> None:
        try:
            target(i)
        except BaseException as exc:  # noqa: BLE001 - recorded and asserted on below
            errors.append(exc)

    threads = [threading.Thread(target=wrapped, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


def _security(i: int) -> SecurityRef:
    return SecurityRef(security_id=f"s{i:03d}", name=f"Security {i}", asset_class="equity", currency="EUR")


def test_concurrent_save_security_keeps_every_record(tmp_path):
    store = PortfolioStore(tmp_path)

    errors = _run_in_threads(lambda i: store.save_security(_security(i)), WRITERS)

    assert errors == []
    assert len(store.list_securities()) == WRITERS


def test_concurrent_saves_never_expose_a_truncated_file_to_readers(tmp_path):
    """The other half of the same defect: `Path.write_text` truncates
    before writing, so a reader could see zero bytes of a file that is
    valid JSON before and after. Readers here run against the file while
    writers hammer it."""
    store = PortfolioStore(tmp_path)
    store.save_security(_security(0))
    stop = threading.Event()
    read_errors: list[BaseException] = []

    def reader() -> None:
        while not stop.is_set():
            try:
                store.list_securities()
            except BaseException as exc:  # noqa: BLE001
                read_errors.append(exc)
                return

    readers = [threading.Thread(target=reader) for _ in range(4)]
    for t in readers:
        t.start()
    try:
        write_errors = _run_in_threads(lambda i: store.save_security(_security(i)), WRITERS)
    finally:
        stop.set()
        for t in readers:
            t.join()

    assert write_errors == []
    assert read_errors == []


def test_concurrent_saves_across_different_registries_do_not_block_each_other(tmp_path):
    """The lock is per file, not per store: a portfolio save and a company
    save touch different files and must both land."""
    store = PortfolioStore(tmp_path)

    def save_pair(i: int) -> None:
        store.save_portfolio(Portfolio(portfolio_id=f"p{i:03d}", name=f"P{i}"))
        store.save_company(CompanyRef(company_id=f"c{i:03d}", name=f"C{i}"))

    errors = _run_in_threads(save_pair, WRITERS)

    assert errors == []
    assert len(store.list_portfolios()) == WRITERS
    assert len(store.list_companies()) == WRITERS


def test_snapshot_write_is_atomic_for_a_concurrent_reader(tmp_path):
    """A re-pull for a date already on disk overwrites that snapshot file
    whole; a reader must see one pull or the other, never a prefix."""
    store = PortfolioStore(tmp_path)
    holdings = [
        Holding(
            portfolio_id="p1", security_id=f"s{i}", as_of_date="2026-01-31",
            quantity=1.0, price=10.0, market_value=10.0, market_value_eur=10.0,
        )
        for i in range(200)
    ]
    store.save_snapshot("p1", "2026-01-31", holdings)
    stop = threading.Event()
    short_reads: list[int] = []

    def reader() -> None:
        while not stop.is_set():
            count = len(store.load_snapshot("p1", "2026-01-31"))
            if count != len(holdings):
                short_reads.append(count)
                return

    readers = [threading.Thread(target=reader) for _ in range(4)]
    for t in readers:
        t.start()
    try:
        errors = _run_in_threads(lambda _i: store.save_snapshot("p1", "2026-01-31", holdings), 20)
    finally:
        stop.set()
        for t in readers:
            t.join()

    assert errors == []
    assert short_reads == []


def _theme() -> ThemeDefinition:
    return ThemeDefinition(name="Grid flexibility", description="Demand-side flexibility assets.")


def test_concurrent_new_version_assigns_one_version_per_edit(tmp_path):
    """Each edit must get its own version file. Previously they all read
    the same current version and wrote the same v2, so the last writer's
    edit was the only one kept -- in a store whose entire premise is that
    a version, once written, is never overwritten."""
    store = TaxonomyStore(tmp_path)
    taxonomy = store.create("Grid flexibility", _theme(), DerivationMethod.MANUAL)
    edits = 8

    errors = _run_in_threads(
        lambda i: store.new_version(taxonomy.taxonomy_id, _theme(), DerivationMethod.MANUAL, source_notes=f"edit {i}"),
        edits,
    )

    assert errors == []
    versions = store.list_versions(taxonomy.taxonomy_id)
    assert [v.version for v in versions] == list(range(1, edits + 2))
    assert store.get(taxonomy.taxonomy_id).version == edits + 1
    # Every edit's own note survived: none was overwritten by another.
    assert sorted(v.source_notes for v in versions[1:]) == sorted(f"edit {i}" for i in range(edits))


def test_writing_an_existing_version_file_is_refused(tmp_path):
    """The O_EXCL guard itself: a second writer landing on a version
    number that already exists fails loudly rather than replacing it."""
    store = TaxonomyStore(tmp_path)
    taxonomy = store.create("Grid flexibility", _theme(), DerivationMethod.MANUAL)

    with pytest.raises(FileExistsError):
        store._write_new_version(taxonomy)


def test_ratify_rewrites_its_version_atomically(tmp_path):
    """Ratification is the one write that legitimately replaces a version
    file, so it can't use O_EXCL -- but it must still never leave the file
    unparseable (list_versions silently skips a version it can't read)."""
    store = TaxonomyStore(tmp_path)
    taxonomy = store.create("Grid flexibility", _theme(), DerivationMethod.MANUAL)

    ratified = store.ratify(taxonomy.taxonomy_id, 1, ratified_by="analyst@example.com")

    assert ratified.status.value == "ratified"
    on_disk = json.loads(store._version_path(taxonomy.taxonomy_id, 1).read_text())
    assert on_disk["ratified_by"] == "analyst@example.com"
    assert [v.version for v in store.list_versions(taxonomy.taxonomy_id)] == [1]
    assert not list(store._dir(taxonomy.taxonomy_id).glob(".tmp_*"))


# --- across processes, not just across threads ---------------------------


def test_keyed_lock_serializes_across_processes(tmp_path):
    """The boundary a threading.RLock cannot cover, and one this app
    actually crosses: `arp ...` CLI commands write the same runs/,
    portfolios/, engagements/ and taxonomies/ directories as a live API
    process, and `uvicorn --workers N` would put several API processes on
    them. Two subprocesses take the same keyed lock and record when they
    held it; their intervals must not overlap.
    """
    import subprocess
    import sys
    import textwrap

    lock_dir = tmp_path / "locked"
    lock_dir.mkdir()
    script = textwrap.dedent(
        """
        import json, sys, time
        from pathlib import Path
        sys.path.insert(0, %r)
        from arp.storage.locks import KeyedLock

        lock_dir = Path(sys.argv[1])
        label = sys.argv[2]
        locks = KeyedLock(lock_path=lambda key: lock_dir / f"{key}.lock")
        with locks.acquire("shared"):
            entered = time.monotonic()
            time.sleep(0.4)
            left = time.monotonic()
        (lock_dir / f"{label}.json").write_text(json.dumps({"entered": entered, "left": left}))
        """
    ) % str(Path(__file__).resolve().parents[1])
    script_path = tmp_path / "hold_lock.py"
    script_path.write_text(script)

    procs = [
        subprocess.Popen([sys.executable, str(script_path), str(lock_dir), label])
        for label in ("first", "second")
    ]
    for proc in procs:
        assert proc.wait(timeout=60) == 0

    spans = sorted(
        (json.loads((lock_dir / f"{label}.json").read_text()) for label in ("first", "second")),
        key=lambda s: s["entered"],
    )
    # The second process cannot have entered before the first one left.
    assert spans[0]["left"] <= spans[1]["entered"], f"overlapping hold windows: {spans}"


def test_a_nested_acquire_of_the_same_key_does_not_release_early(tmp_path):
    """RLock reentrancy has to extend to the file lock, or an inner
    `with` block exiting would drop the flock while the outer one still
    believes it holds it."""
    from arp.storage.locks import KeyedLock

    locks = KeyedLock(lock_path=lambda key: tmp_path / f"{key}.lock")

    with locks.acquire("k"):
        with locks.acquire("k"):
            assert "k" in locks._files
        assert "k" in locks._files, "inner exit released the cross-process lock"
    assert "k" not in locks._files


def test_run_store_and_engagement_store_lock_files_stay_out_of_listings(tmp_path):
    """The lock files live beside the data they guard, so they must not
    show up as runs, snapshots, taxonomy versions or observation keys."""
    from arp.schemas.common import JobStatus, RunManifest
    from arp.storage.run_store import RunStore

    run_store = RunStore(tmp_path / "runs")
    run_store.save_manifest(RunManifest(run_id="run_1", run_type="extraction", status=JobStatus.COMPLETED))
    with run_store.lock("run_1"):
        pass

    portfolio_store = PortfolioStore(tmp_path / "portfolios")
    portfolio_store.save_portfolio(Portfolio(portfolio_id="p1", name="P1"))
    portfolio_store.save_snapshot("p1", "2026-01-31", [
        Holding(portfolio_id="p1", security_id="s1", as_of_date="2026-01-31", quantity=1.0, price=1.0,
                market_value=1.0, market_value_eur=1.0)
    ])

    taxonomy_store = TaxonomyStore(tmp_path / "taxonomies")
    taxonomy = taxonomy_store.create("T", _theme(), DerivationMethod.MANUAL)

    assert [m.run_id for m in run_store.list_runs()] == ["run_1"]
    assert portfolio_store.list_snapshot_dates("p1") == ["2026-01-31"]
    assert [p.portfolio_id for p in portfolio_store.list_portfolios()] == ["p1"]
    assert [v.version for v in taxonomy_store.list_versions(taxonomy.taxonomy_id)] == [1]
    assert taxonomy_store.list_all()[0].taxonomy_id == taxonomy.taxonomy_id
