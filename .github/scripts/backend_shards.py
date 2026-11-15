"""Check that CI's backend shards together ran exactly the tests a single run collects.

Each shard directory holds `ran.txt` (written by pytest_shard.py: `backend shard: K/N`, then the node
ids that ran) and `collected.txt` (raw `pytest --collect-only -q` output). Prints
`backend tests: <a> of <b>` and exits 1 with `backend shards: missing K/N`, `backend tests: duplicate
<id>` or `backend tests: <a> of <b>` lines when the parts are not exactly 1..N or the node ids run are
not exactly the collected list.

Usage: python3 backend_shards.py N DIR     (DIR/<any>/ran.txt and DIR/<any>/collected.txt)
       python3 backend_shards.py --times DIR > .github/scripts/backend_test_times.json
                                         (merge the shards' DIR/<any>/times.json, to rebalance the split)
       python3 backend_shards.py --selftest
"""

import json
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

HEADER = re.compile(r"backend shard: (\d+)/(\d+)")
COLLECTED = re.compile(r"(\d+) tests? collected")
NODE_ID = re.compile(r"[^\s:]+\.py::")


def parse_collected(text: str) -> list[str]:
    """Node ids from `pytest --collect-only -q`, checked against its `N tests collected` line."""
    ids = [line for line in text.splitlines() if NODE_ID.match(line)]
    total = COLLECTED.search(text)
    if not total or int(total[1]) != len(ids):
        raise ValueError(f"collect-only output lists {len(ids)} node ids but says {total[0] if total else 'nothing'}")
    return ids


def check(n: int, reports: list[str], collected: list[str]) -> tuple[list[str], bool]:
    out: list[str] = []
    parts: set[int] = set()
    ran: list[str] = []
    for text in reports:
        lines = [line for line in text.splitlines() if line]
        m = HEADER.fullmatch(lines[0]) if lines else None
        if not m or int(m[2]) != n:
            out.append(f"backend shards: bad report header {lines[0] if lines else '(empty)'!r}")
            continue
        parts.add(int(m[1]))
        ran += lines[1:]

    lists = []
    for text in collected:
        try:
            lists.append(parse_collected(text))
        except ValueError as e:
            out.append(f"backend tests: {e}")
    if len({tuple(sorted(c)) for c in lists}) > 1:
        out.append("backend tests: shards collected different lists")
    want = lists[0] if lists else []

    out += [f"backend shards: missing {k}/{n}" for k in range(1, n + 1) if k not in parts]
    out += [f"backend shards: unexpected {k}/{n}" for k in sorted(parts) if not 1 <= k <= n]
    out += [f"backend tests: duplicate {nodeid}" for nodeid, c in Counter(ran).items() if c > 1]
    exact = bool(want) and Counter(ran) == Counter(want)
    summary = f"backend tests: {len(ran)} of {len(want)}"
    if not exact:
        out += [f"backend tests: not run {nodeid}" for nodeid in sorted(set(want) - set(ran))[:20]]
        out += [f"backend tests: not collected {nodeid}" for nodeid in sorted(set(ran) - set(want))[:20]]
    ok = exact and not out
    return [summary, *out], ok


def main(n: int, root: Path) -> int:
    reports = [p.read_text() for p in sorted(root.glob("*/ran.txt"))]
    collected = [p.read_text() for p in sorted(root.glob("*/collected.txt"))]
    if not collected:
        print("backend tests: no collected list from any shard")
    lines, ok = check(n, reports, collected)
    print("\n".join(lines))
    return 0 if ok and collected else 1


def selftest() -> None:
    a, b, c = "tests/test_a.py::test_x", "tests/test_a.py::test_y[1]", "tests/b/test_b.py::T::test_z"
    coll = f"{a}\n{b}\n{c}\n\n3 tests collected in 0.1s\n"

    def run(reports, collected=(coll, coll)):
        return check(2, list(reports), list(collected))

    assert run(["backend shard: 1/2\n" + a + "\n" + b, "backend shard: 2/2\n" + c]) == (
        ["backend tests: 3 of 3"], True)
    lines, ok = run(["backend shard: 1/2\n" + a + "\n" + b + "\n" + c, "backend shard: 1/2\n"])
    assert not ok and "backend shards: missing 2/2" in lines, lines
    lines, ok = run(["backend shard: 1/2\n" + a + "\n" + b, "backend shard: 2/2\n" + c + "\n" + a])
    assert not ok and f"backend tests: duplicate {a}" in lines and "backend tests: 4 of 3" in lines, lines
    lines, ok = run(["backend shard: 1/2\n" + a, "backend shard: 2/2\n" + c])
    assert not ok and "backend tests: 2 of 3" in lines and f"backend tests: not run {b}" in lines, lines
    lines, ok = run(["backend shard: 1/2\n" + a + "\n" + b])
    assert not ok and "backend shards: missing 2/2" in lines, lines
    lines, ok = run(["backend shard: 1/4\n" + a + "\n" + b, "backend shard: 2/2\n" + c])
    assert not ok and any(line.startswith("backend shards: bad report header") for line in lines), lines
    lines, ok = run(["backend shard: 1/2\n" + a + "\n" + b, "backend shard: 2/2\n" + c], (coll, f"{a}\n\n1 test collected\n"))
    assert not ok and "backend tests: shards collected different lists" in lines, lines
    lines, ok = run(["backend shard: 1/2\n" + a + "\n" + b, "backend shard: 2/2\n" + c], (f"{a}\n{b}\n\n3 tests collected\n",))
    assert not ok and any("but says 3 tests collected" in line for line in lines), lines
    assert parse_collected("warn\n\ntests/t.py::a[x y]\n\n== warnings ==\ntests/t.py:3\n  w.py:1: W\n1 test collected in 1s\n") == [
        "tests/t.py::a[x y]"]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for k, ids in ((1, [a, b]), (2, [c])):
            (root / f"shard-{k}").mkdir()
            (root / f"shard-{k}" / "ran.txt").write_text(f"backend shard: {k}/2\n" + "\n".join(ids) + "\n")
            (root / f"shard-{k}" / "collected.txt").write_text(coll)
        assert main(2, root) == 0
        (root / "shard-2" / "ran.txt").unlink()
        assert main(2, root) == 1
    print("selftest ok")


def merge_times(root: Path) -> str:
    times = {}
    for p in sorted(root.glob("*/times.json")):
        times.update(json.loads(p.read_text()))
    return json.dumps(dict(sorted(times.items())), indent=0) + "\n"


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    elif sys.argv[1] == "--times":
        sys.stdout.write(merge_times(Path(sys.argv[2])))
    else:
        sys.exit(main(int(sys.argv[1]), Path(sys.argv[2])))
