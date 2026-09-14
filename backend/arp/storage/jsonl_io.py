"""Shared JSONL read/append used by every file-based store.

`RunStore.read_jsonl` and `PortfolioStore._read_jsonl` used to disagree
about a line that won't decode: the first skipped it, the second raised,
so one bad line in `news/items.jsonl` or an observations file took out
the whole read (and with it an unrelated API response). They now share
this reader, which skips.

Skipping is the right default for these files: every one of them is an
append-only log whose readers fold over whatever is there (results,
review decisions, observations, news, alert events). A line that doesn't
decode is a torn tail from an interrupted append, not a record with
meaning -- dropping it degrades gracefully, while raising discards the
thousands of intact records in front of it.
"""

from __future__ import annotations

import json
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    """Every decodable line of a JSONL file, in order. A missing file is
    an empty list (an append-only log that has never been appended to is
    not an error); a line that won't decode is skipped."""
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def append_jsonl(path: Path, row: dict) -> None:
    """Appends one record as a single line. Callers that share a file
    across threads take their store's own lock around this (see
    PortfolioStore._append_jsonl): O_APPEND keeps each write at the end of
    the file, but a row long enough to exceed the pipe buffer is not
    guaranteed to land in one piece, which is what produces the torn
    lines read_jsonl tolerates."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")
