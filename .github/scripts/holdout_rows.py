#!/usr/bin/env python3
"""Read the `Rows:` line of a PR body for the Holdout acceptance run.

usage: holdout_rows.py < body      prints the row IDs, comma-separated (empty when the body has no Rows: line)
       holdout_rows.py --selftest

The line lists row IDs with commas: `Rows: AC-1, AC-4, AC-4b`. An ID is `AC-<number>` with an optional
lower-case suffix. A Rows: line that is anything else (a range such as `AC-1 to AC-19`, prose after the list,
bold or quoted markup, an empty list) exits 1 with a message, so a PR never quietly runs fewer rows than it owes.
"""

import re
import sys

ID = r"AC-\d+[a-z]*"
LINE = re.compile(rf"^Rows:[ \t]*({ID}(?:[ \t]*,[ \t]*{ID})*)[ \t]*,?[ \t]*$")
ROWS_LIKE = re.compile(r"^[\s>*_]*Rows:")
UNREADABLE = "Holdout acceptance: unreadable Rows: line; list the row IDs with commas, on a line of its own: Rows: AC-1, AC-4, AC-4b"


def parse(body):
    """Return (rows, error): rows is the comma-separated IDs ("" when no Rows: line), error a message or None."""
    for line in body.splitlines():
        line = line.rstrip()
        if not ROWS_LIKE.match(line):
            continue
        if m := LINE.match(line):
            return ",".join(re.findall(ID, m.group(1))), None
        return "", f"{UNREADABLE}\n  got: {line}"
    return "", None


def selftest():
    cases = [
        ("Spec: x\n", ""),
        ("Spec: x\nRows: AC-1, AC-4\n", "AC-1,AC-4"),
        ("Rows: AC-1, AC-2, AC-3, AC-4, AC-4b, AC-5, AC-6, AC-7, AC-8\r\n", "AC-1,AC-2,AC-3,AC-4,AC-4b,AC-5,AC-6,AC-7,AC-8"),
        ("Rows: AC-1, AC-7, AC-7b, AC-8", "AC-1,AC-7,AC-7b,AC-8"),
        ("Rows:AC-10b,AC-11 , AC-15b ", "AC-10b,AC-11,AC-15b"),
        ("Rows: AC-3,", "AC-3"),
        ("Rows: AC-1\nRows: AC-2", "AC-1"),
        ("Some prose about Rows: here\n", ""),
        ("Rows: AC-1 to AC-19", None),
        ("Rows: AC-1-AC-19", None),
        ("Rows: AC-1..AC-19", None),
        ("Rows: AC-1, AC-4 (slice 1)", None),
        ("Rows: AC-1 AC-4", None),
        ("Rows: AC-7B", None),
        ("Rows:", None),
        ("Rows: all", None),
        ("**Rows:** AC-1", None),
        ("> Rows: AC-1", None),
        ("  Rows: AC-1", None),
    ]
    for body, want in cases:
        rows, err = parse(body)
        got = None if err else rows
        assert got == want, (body, rows, err)
        assert (err is None) == (want is not None), (body, err)
    print("selftest ok")


def main(argv):
    if argv[1:] == ["--selftest"]:
        return selftest()
    rows, err = parse(sys.stdin.read())
    if err:
        print(err)
        return 1
    print(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
