"""pytest plugin for CI's backend shards: run part K of N of the suite and record what ran.

Usage (from backend/): PYTHONPATH=../.github/scripts pytest -p pytest_shard --shard K/N --shard-report FILE

The unit is the test file, so module fixtures and in-file test order stay as in a single run. Files go
largest first (by test count) to the part with the fewest tests, so the split is the same on every run
of the same commit and a new file lands in some part on its own. FILE gets `backend shard: K/N`, then
one node id per test that entered setup (passed, failed, errored or skipped). The CI job
`Backend (lint + tests)` checks these files with backend_shards.py.
"""

from collections import Counter

import pytest


def pytest_addoption(parser):
    parser.addoption("--shard", default=None, help="K/N: run only part K of N (1-based)")
    parser.addoption("--shard-report", default=None, help="write the part and the node ids run to this file")


def parse_shard(value: str) -> tuple[int, int]:
    try:
        k, n = (int(x) for x in value.split("/"))
    except ValueError:
        raise pytest.UsageError(f"invalid --shard {value!r}: expected K/N") from None
    if not 1 <= k <= n:
        raise pytest.UsageError(f"invalid --shard {value!r}: need 1 <= K <= N")
    return k, n


def assign(files: Counter, n: int) -> dict[str, int]:
    """Map each file to a part 1..n: largest file first, into the part with the fewest tests so far."""
    load = [0] * n
    part = {}
    for path, count in sorted(files.items(), key=lambda pc: (-pc[1], pc[0])):
        i = load.index(min(load))
        part[path] = i + 1
        load[i] += count
    return part


def pytest_configure(config):
    value = config.getoption("--shard")
    config._shard = parse_shard(value) if value else None


@pytest.hookimpl(trylast=True)  # split what is left after -m/-k deselection, like --collect-only shows it
def pytest_collection_modifyitems(config, items):
    if not config._shard:
        return
    k, n = config._shard
    part = assign(Counter(item.nodeid.split("::")[0] for item in items), n)
    keep = [item for item in items if part[item.nodeid.split("::")[0]] == k]
    drop = [item for item in items if part[item.nodeid.split("::")[0]] != k]
    if drop:
        config.hook.pytest_deselected(items=drop)
    items[:] = keep


_RAN: list[str] = []


def pytest_runtest_logreport(report):
    if report.when == "setup":
        _RAN.append(report.nodeid)


def pytest_sessionfinish(session):
    config = session.config
    path = config.getoption("--shard-report")
    if not path or not config._shard:
        return
    k, n = config._shard
    with open(path, "w") as f:
        f.write(f"backend shard: {k}/{n}\n")
        f.writelines(f"{nodeid}\n" for nodeid in _RAN)
