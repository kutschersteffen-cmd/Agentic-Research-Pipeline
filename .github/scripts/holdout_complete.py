#!/usr/bin/env python3
"""Check that the shards of one full hidden-test run add up to the whole suite (spec holdout-faster-runs).

usage: holdout_complete.py <N> <list file> <shard output>...
       holdout_complete.py --selftest

<list file> is the output of `run.py --list` (one row ID per line). Each shard output holds that shard's
`holdout shard: K/N` line and its result lines (one per row, ending in pass or fail). Prints
`holdout rows: <reported> of <listed>`, plus `holdout shards: missing K/N` for each part no shard reported and
`holdout rows: duplicate <row ID>` for each row reported twice. Exits 1 on any of those, or when the
reported rows are not exactly the listed ones; 0 otherwise.
"""

import re
import sys

SHARD = re.compile(r"^holdout shard: (\d+)/(\d+)\s*$")
RESULT = re.compile(r"\b(pass|fail)\s*$")


def row_id(line, listed):
    """The listed ID a result line starts with (longest match, ending at a word boundary); else the line."""
    best = ""
    for rid in listed:
        rest = line[len(rid):]
        if line.startswith(rid) and len(rid) > len(best) and not re.match(r"[\w-]", rest):
            best = rid
    return best or line


def check(n, listed, outputs):
    shards, rows, out = set(), [], []
    for text in outputs:
        for line in text.splitlines():
            line = line.rstrip()
            if m := SHARD.match(line):
                if int(m.group(2)) == n:
                    shards.add(int(m.group(1)))
            elif RESULT.search(line):
                rows.append(row_id(line, listed))
    out.append(f"holdout rows: {len(rows)} of {len(listed)}")
    out += [f"holdout shards: missing {k}/{n}" for k in range(1, n + 1) if k not in shards]
    seen = set()
    for r in rows:
        if r in seen:
            out.append(f"holdout rows: duplicate {r}")
        seen.add(r)
    ok = len(out) == 1 and len(rows) == len(listed) and seen == set(listed)
    return ok, out


def selftest():
    listed = ["s AC-1", "s AC-12", "r AC-2"]
    good = ["holdout shard: 1/2\ns AC-1: pass\ns AC-12: fail\nlogin: done in 3 s", "holdout shard: 2/2\nr AC-2: pass"]
    cases = [
        (good, True, ["holdout rows: 3 of 3"]),
        ([good[0], "holdout shard: 1/2\nr AC-2: pass"], False, ["holdout rows: 3 of 3", "holdout shards: missing 2/2"]),
        (good + ["holdout shard: 1/2\ns AC-1: pass"], False, ["holdout rows: 4 of 3", "holdout rows: duplicate s AC-1"]),
        ([good[0], "holdout shard: 2/2"], False, ["holdout rows: 2 of 3"]),
        ([good[0], "holdout shard: 2/2\nx AC-9: pass"], False, ["holdout rows: 3 of 3"]),
        ([good[0]], False, ["holdout rows: 2 of 3", "holdout shards: missing 2/2"]),
    ]
    for outputs, want_ok, want_out in cases:
        got = check(2, listed, outputs)
        assert got == (want_ok, want_out), (outputs, got)
    assert row_id("s AC-12 pass", listed) == "s AC-12"
    print("selftest ok")


def main(argv):
    if argv[1:] == ["--selftest"]:
        return selftest()
    n, list_file, *files = argv[1:]
    with open(list_file) as f:
        listed = [line.strip() for line in f if line.strip()]
    outputs = []
    for name in files:
        with open(name) as f:
            outputs.append(f.read())
    ok, out = check(int(n), listed, outputs)
    print("\n".join(out))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
