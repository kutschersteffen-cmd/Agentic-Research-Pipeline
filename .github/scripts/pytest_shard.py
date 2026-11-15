"""pytest plugin for CI's backend shards: run part K of N of the suite and record what ran.

Usage (from backend/): PYTHONPATH=../.github/scripts pytest -p pytest_shard --shard K/N --shard-report FILE
                       [--shard-times backend_test_times.json]

The unit is the test file, so module fixtures and in-file test order stay as in a single run. Files go
heaviest first to the part with the least weight so far. A file's weight is its seconds in the times
file, or, for a file not in it, its test count times the mean seconds per test of the files that are.
The split is the same on every run of the same commit, and a new file lands in some part on its own.

FILE gets `backend shard: K/N`, then one node id per test that entered setup (passed, failed, errored
or skipped); `times.json` next to it gets this part's seconds per file. The CI job
`Backend (lint + tests)` checks the FILEs with backend_shards.py.
"""

import json
from collections import Counter, defaultdict
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


def assign(counts: Counter, n: int, times: dict[str, float]) -> dict[str, int]:
    """Map each file to a part 1..n: heaviest file first, into the part with the least weight so far."""
    timed = [path for path in counts if path in times]
    per_test = sum(times[p] for p in timed) / sum(counts[p] for p in timed) if timed else 1.0
    weight = {path: times.get(path, count * per_test) for path, count in counts.items()}
    load = [0.0] * n
    part = {}
    for path in sorted(weight, key=lambda p: (-weight[p], p)):
        i = load.index(min(load))
        part[path] = i + 1
        load[i] += weight[path]
    return part


def _file(nodeid: str) -> str:
    return nodeid.split("::")[0]


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
    part = assign(Counter(_file(item.nodeid) for item in items), n, times)
    keep = [item for item in items if part[_file(item.nodeid)] == k]
    drop = [item for item in items if part[_file(item.nodeid)] != k]
    if drop:
        config.hook.pytest_deselected(items=drop)
    items[:] = keep


_RAN: list[str] = []
_SECONDS: defaultdict[str, float] = defaultdict(float)


def pytest_runtest_logreport(report):
    if report.when == "setup":
        _RAN.append(report.nodeid)
    _SECONDS[_file(report.nodeid)] += report.duration


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
    c = Counter({"a.py": 10, "b.py": 10, "c.py": 1, "d.py": 1})
    assert assign(c, 2, {}) == {"a.py": 1, "b.py": 2, "c.py": 1, "d.py": 2}
    # b.py is untimed: 10 tests x 10 s/test (mean of a.py and c.py) = 100, as heavy as c.py
    assert assign(c, 2, {"c.py": 100.0, "a.py": 10.0}) == {"b.py": 1, "c.py": 2, "a.py": 1, "d.py": 2}
    print("selftest ok")
