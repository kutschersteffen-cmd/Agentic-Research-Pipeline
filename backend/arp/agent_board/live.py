"""Live pointers (spec agent-board, Phase 2 "Live pointers (D9)"): JSON Pointers (RFC 6901) into the thread data,
resolved on every read and write."""

from __future__ import annotations

import json
from typing import Any

_MISSING = object()


class PointerInvalid(ValueError):
    pass


def check_pointer(p: Any) -> str:
    """The pointer's form: a string of 1 to 200 characters starting with `/`."""
    if not isinstance(p, str) or not 1 <= len(p) <= 200 or not p.startswith("/"):
        raise PointerInvalid("live must be a JSON Pointer starting with /")
    return p


def _tokens(p: str) -> list[str]:
    return [t.replace("~1", "/").replace("~0", "~") for t in p.split("/")[1:]]


def _index(token: str, n: int) -> int | None:
    if not token.isdigit() or (len(token) > 1 and token[0] == "0") or not token.isascii():
        return None
    i = int(token)
    return i if i < n else None


def resolve(p: str, data: Any) -> Any:
    """The pointer's value, or `_MISSING` when it does not resolve."""
    node = data
    for t in _tokens(p):
        if isinstance(node, dict):
            if t not in node:
                return _MISSING
            node = node[t]
        elif isinstance(node, list):
            i = _index(t, len(node))
            if i is None:
                return _MISSING
            node = node[i]
        else:
            return _MISSING
    return node


def step_of(p: str, data: Any) -> int | None:
    """`live_step`: the `seq` of `steps[n]` when the pointer starts with `steps` and an index that exists."""
    tokens = _tokens(p)
    steps = data.get("steps") if isinstance(data, dict) else None
    if len(tokens) < 2 or tokens[0] != "steps" or not isinstance(steps, list):
        return None
    i = _index(tokens[1], len(steps))
    if i is None or not isinstance(steps[i], dict):
        return None
    return steps[i].get("seq")


def rows_of(p: str, data: Any) -> tuple[list[dict], str | None]:
    """The pointer's list of objects, or `[]` and the error message."""
    value = resolve(p, data)
    if value is _MISSING:
        return [], f"live data not found: {p}"
    if not isinstance(value, list) or not all(isinstance(r, dict) for r in value):
        return [], f"live data is not a list of rows: {p}"
    return value, None


def number_of(p: str, data: Any) -> tuple[int | float | None, str | None]:
    """The pointer's number, or `None` and the error message."""
    value = resolve(p, data)
    if value is _MISSING:
        return None, f"live data not found: {p}"
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None, f"live data is not a number: {p}"
    return value, None


MAX_CELL_CHARS = 1000


def cell(v: Any) -> Any:
    """A live table cell: numbers and null as they are; a string, or any other value as its compact JSON text, cut to
    1 000 characters followed by `…` when longer (Amendment 1b)."""
    if v is None or (isinstance(v, int | float) and not isinstance(v, bool)):
        return v
    text = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return text[:MAX_CELL_CHARS] + "…" if len(text) > MAX_CELL_CHARS else text
