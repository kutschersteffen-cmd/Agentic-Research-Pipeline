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
import logging
from collections.abc import Iterator
from pathlib import Path

logger = logging.getLogger(__name__)
_WARNED: set[tuple[str, int]] = set()  # (path, line) already reported as damaged, once per process


def read_jsonl(path: Path) -> list[dict]:
    """Every decodable line of a JSONL file, in order. A missing file is
    an empty list (an append-only log that has never been appended to is
    not an error); a line that won't decode is skipped."""
    if not path.exists():
        return []
    rows: list[dict] = []
    # encoding is explicit for the same reason as in atomic_io: the
    # locale default is cp1252 on Western-European Windows, and a
    # UnicodeDecodeError is not a json.JSONDecodeError, so a non-ASCII
    # byte would propagate past the skip below and take out the whole read.
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def read_jsonl_numbered(path: Path) -> Iterator[tuple[int, object]]:
    """(1-based line number, decoded value) for every decodable line, as read_jsonl skips; the numbers count every
    line of the file, blank and undecodable ones included. The value can be any JSON value, not only an object."""
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if line := line.strip():
                try:
                    yield n, json.loads(line)
                except json.JSONDecodeError:
                    continue


def complete_rows(path: Path, needs) -> Iterator[dict]:
    """The JSON objects of `path` that have every key `needs(row)` names. Any other decodable line is damaged: it is
    skipped with one WARNING `Skipped damaged line <n> in <path>` per (path, line) and process."""
    for n, row in read_jsonl_numbered(path):
        if isinstance(row, dict) and all(k in row for k in needs(row)):
            yield row
        elif (str(path), n) not in _WARNED:
            _WARNED.add((str(path), n))
            logger.warning("Skipped damaged line %d in %s", n, path)


def append_jsonl(path: Path, row: dict) -> None:
    """Appends one record as a single line. Callers that share a file
    across threads take their store's own lock around this (see
    PortfolioStore._append_jsonl): O_APPEND keeps each write at the end of
    the file, but a row long enough to exceed the pipe buffer is not
    guaranteed to land in one piece, which is what produces the torn
    lines read_jsonl tolerates."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
