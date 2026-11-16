"""pytest plugin for CI's backend shards: run part K of N of the suite and record what ran.

Usage (from backend/): PYTHONPATH=../.github/scripts pytest -p pytest_shard --shard=K/N --shard-report=FILE
                       [--shard-times=backend_test_times.json]
Write the options with `=`: a separate existing path argument moves pytest's rootdir, so node ids and the
backend's pytest settings would change.

The unit is the test (node id). Tests stay in collection order and are cut into N blocks of about equal
weight. Only a file that straddles a block end (at most N-1 files) is split, and only its module fixtures
run twice. A test's weight is its seconds in the times file, or, for a test not in it, the
mean seconds per test of the tests that are. The split is the same on every run of the same commit, and a
new test lands in some part on its own.

FILE gets `backend shard: K/N`, then one node id per test that entered setup (passed, failed, errored
or skipped); `times.json` next to it gets this part's seconds per test. The CI job
`Backend (lint + tests)` checks the FILEs with backend_shards.py.
"""

import json
from collections import defaultdict
from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption("--shard", default=None, help="K/N: run only part K of N (1-based)")
    parser.addoption("--shard-report", default=None, help="write the part and the node ids run to this file")
    parser.addoption("--shard-times", default=None, help="JSON {test file: seconds} to balance the parts")


def parse_shard(value: str) -> tuple[int, int]:
    try:
        k, n = (int(x) for x in value.split("/"))
    except ValueError:
        raise pytest.UsageError(f"invalid --shard {value!r}: expected K/N") from None
    if not 1 <= k <= n:
        raise pytest.UsageError(f"invalid --shard {value!r}: need 1 <= K <= N")
    return k, n


def assign(nodeids: list[str], n: int, times: dict[str, float]) -> list[int]:
    """Part 1..n for each test: cut the tests, in order, into n blocks of about equal weight."""
    timed = [t for t in nodeids if t in times]
    mean = sum(times[t] for t in timed) / len(timed) if timed else 0.0
    weight = [times.get(t, mean) for t in nodeids]
    if not sum(weight):  # nothing timed or all 0 s: count tests instead
        weight = [1.0] * len(nodeids)
    total, done, parts = sum(weight), 0.0, []
    for w in weight:
        parts.append(min(n, int((done + w / 2) * n / total) + 1))  # the block holding this test's midpoint
        done += w
    return parts


def pytest_configure(config):
    value = config.getoption("--shard")
    config._shard = parse_shard(value) if value else None


@pytest.hookimpl(trylast=True)  # split what is left after -m/-k deselection, like --collect-only shows it
def pytest_collection_modifyitems(config, items):
    if not config._shard:
        return
    k, n = config._shard
    times_path = config.getoption("--shard-times")
    times = json.loads(Path(times_path).read_text()) if times_path else {}
    parts = assign([item.nodeid for item in items], n, times)
    keep = [item for item, p in zip(items, parts) if p == k]
    drop = [item for item, p in zip(items, parts) if p != k]
    if drop:
        config.hook.pytest_deselected(items=drop)
    items[:] = keep


_RAN: list[str] = []
_SECONDS: defaultdict[str, float] = defaultdict(float)


def pytest_runtest_logreport(report):
    if report.when == "setup":
        _RAN.append(report.nodeid)
    _SECONDS[report.nodeid] += report.duration


def pytest_sessionfinish(session):
    config = session.config
    path = config.getoption("--shard-report")
    if not path or not config._shard:
        return
    k, n = config._shard
    with open(path, "w") as f:
        f.write(f"backend shard: {k}/{n}\n")
        f.writelines(f"{nodeid}\n" for nodeid in _RAN)
    times = {p: round(s, 2) for p, s in sorted(_SECONDS.items())}
    (Path(path).parent / "times.json").write_text(json.dumps(times, indent=0) + "\n")


if __name__ == "__main__":  # self-check of the split
    ids = ["a::1", "a::2", "b::1", "b::2"]
    assert assign(ids, 2, {}) == [1, 1, 2, 2]
    assert assign(ids, 2, {"a::1": 9.0, "b::2": 1.0}) == [1, 2, 2, 2]  # untimed a::2, b::1 weigh the mean, 5 s
    assert assign(ids, 4, {t: 0.0 for t in ids}) == [1, 2, 3, 4]
    assert assign(ids[:1], 4, {}) == [3]  # fewer tests than parts: the rest stay empty (pytest exits 5)
    print("selftest ok")
