"""Block checks and rendering (spec agent-board, "Block sources and validation" and "Rendering").

`check_block` raises `BlockInvalid` with the spec's message for the first failing check, else returns the block's
`rendered` value, so a write renders a chart once.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import threading
from typing import Any

KINDS = ("note", "table", "chart", "flow")
_OUTSIDE_KEYS = ("url", "href", "loader")


class BlockInvalid(ValueError):
    """`str()` is the 422 detail."""


def _is_number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def storable(node: Any) -> bool:
    """No NUL character or lone surrogate in any string or key, and no NaN or Infinity: Postgres cannot store them."""
    stack = [node]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            stack.extend(node.keys())
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, str):
            if "\x00" in node:
                return False
            try:
                node.encode("utf-8")
            except UnicodeEncodeError:
                return False
        elif isinstance(node, float) and not math.isfinite(node):
            return False
    return True


def check_title(title: Any) -> str:
    if not isinstance(title, str):
        raise BlockInvalid("invalid block")
    title = title.strip()
    if not 1 <= len(title) <= 120:
        raise BlockInvalid("title must be 1 to 120 characters")
    return title


def _outside(node: Any, path: str) -> str | None:
    """The JSON path of the first key or image mark that could load from outside, in document order."""
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}" if path else k
            if k in _OUTSIDE_KEYS:
                return p
            if k == "mark" and (v == "image" or (isinstance(v, dict) and v.get("type") == "image")):
                return p
            if (found := _outside(v, p)) is not None:
                return found
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if (found := _outside(v, f"{path}[{i}]")) is not None:
                return found
    return None


MAX_CHART_ROWS = 5000


def _num(v: Any) -> bool:
    return _is_number(v) and math.isfinite(v)


def _values_rows(values: Any) -> float:
    """Rows of an inline `values`: a list's length, the rows of a JSON array string, or the lines of a CSV/TSV string.
    Anything else (an object, a JSON string that is not an array) is refused before rendering."""
    if values is None:
        return 0
    if isinstance(values, list):
        return len(values)
    if isinstance(values, str):
        try:
            parsed = json.loads(values)
        except ValueError:
            return len(values.splitlines())  # CSV or TSV: \r\n, \r and \n all end a row
        if isinstance(parsed, list):
            return len(parsed)
    raise BlockInvalid("chart does not render: data values must be a list or a CSV, TSV or JSON array string")


def _sequence_rows(seq: dict) -> float:
    """Rows a `sequence` generator makes: (stop - start) / step, step 1 by default; anything unreadable is unbounded."""
    start, stop, step = seq.get("start", 0), seq.get("stop"), seq.get("step", 1)
    if not (_num(start) and _num(stop) and _num(step)) or step == 0:
        return math.inf
    return max(0, math.ceil((stop - start) / step))


def _graticule_rows(g: Any) -> float:
    """Lines a `graticule` generator makes: about 360 / x-step + 180 / y-step for its finest step."""
    if not isinstance(g, dict):
        return 0
    rows = 0.0
    for key in ("step", "stepMinor", "stepMajor"):
        step = g.get(key)
        if step is None:
            continue
        if not (isinstance(step, list) and len(step) == 2 and all(_num(x) and x > 0 for x in step)):
            return math.inf
        rows = max(rows, 360 / step[0] + 180 / step[1])
    return rows


def _too_many_rows(node: Any) -> bool:
    """Any inline `values` (also a named dataset) or data generator (`sequence`, `graticule`) over 5 000 rows."""
    if isinstance(node, dict):
        data = node.get("data")
        if isinstance(data, dict) and (_values_rows(data.get("values")) > MAX_CHART_ROWS
                                       or ("graticule" in data and _graticule_rows(data["graticule"]) > MAX_CHART_ROWS)):
            return True
        if isinstance(node.get("sequence"), dict) and _sequence_rows(node["sequence"]) > MAX_CHART_ROWS:  # data.sequence
            return True
        keyvals = node.get("keyvals")  # impute: `{start?, stop, step?}` is a sequence
        if "impute" in node and isinstance(keyvals, dict) and _sequence_rows(keyvals) > MAX_CHART_ROWS:
            return True
        datasets = node.get("datasets")
        if isinstance(datasets, dict) and any(_values_rows(v) > MAX_CHART_ROWS for v in datasets.values()):
            return True
        return any(_too_many_rows(v) for v in node.values())
    if isinstance(node, list):
        return any(_too_many_rows(v) for v in node)
    return False


def _check_table(source: Any) -> None:
    if not isinstance(source, dict) or not isinstance(source.get("columns"), list) or not isinstance(source.get("rows"), list):
        raise BlockInvalid("invalid block")
    cols, rows = source["columns"], source["rows"]
    if not all(isinstance(c, str) for c in cols):
        raise BlockInvalid("invalid block")
    if not 1 <= len(cols) <= 20:
        raise BlockInvalid("table must have 1 to 20 columns")
    if len(rows) > 200:
        raise BlockInvalid("table exceeds 200 rows")
    for i, row in enumerate(rows, start=1):
        if not isinstance(row, list) or not all(c is None or isinstance(c, str) or _is_number(c) for c in row):
            raise BlockInvalid("invalid block")
        if len(row) != len(cols):
            raise BlockInvalid(f"row {i} has {len(row)} cells, expected {len(cols)}")


RENDER_TIMEOUT_S = 30


class RenderFailed(Exception):
    """`str()` is the first line of why the chart could not be drawn."""


_RENDER_SLOTS = threading.BoundedSemaphore(2)  # at most two render children (about 1 GiB each) at once


def render_chart(source: dict) -> dict[str, str]:
    """Light and dark SVG of the chart with the house theme (D1), drawn in a child process with a memory cap and a
    timeout, so no chart can take the API down. Nothing is cached: a read renders again (spec "Rendering")."""
    with _RENDER_SLOTS:
        try:
            proc = subprocess.run([sys.executable, "-m", "arp.agent_board.render_worker"], input=json.dumps(source),
                                  capture_output=True, text=True, timeout=RENDER_TIMEOUT_S, check=False)
        except subprocess.TimeoutExpired:
            raise RenderFailed(f"rendering took longer than {RENDER_TIMEOUT_S} s") from None
    if proc.returncode != 0:
        lines = [ln for ln in proc.stderr.strip().splitlines() if ln.strip()]
        if proc.returncode == 1 and lines:
            raise RenderFailed(lines[0])
        raise RenderFailed("rendering ran out of memory or crashed")
    out = json.loads(proc.stdout)
    return {"light": out["light"], "dark": out["dark"]}


def render(kind: str, source: Any) -> Any:
    """`rendered` of a stored block: null for note and table, SVGs for a chart, the parsed `Flow` for a flow."""
    if kind == "chart":
        return render_chart(source)
    if kind == "flow":
        from arp.reporting.mermaid_flow import parse_mermaid

        return parse_mermaid(source).model_dump(mode="json")
    return None


def check_block(kind: Any, title: Any, source: Any) -> Any:
    """Raises `BlockInvalid` for the first failing check; returns `rendered`."""
    if not isinstance(kind, str) or not isinstance(title, str):
        raise BlockInvalid("invalid block")
    check_title(title)
    if kind not in KINDS:
        raise BlockInvalid(f"unknown block kind: {kind}")
    if kind == "note":
        if not isinstance(source, str):
            raise BlockInvalid("invalid block")
        if len(source) > 20000:
            raise BlockInvalid("note exceeds 20000 characters")
        return None
    if kind == "table":
        _check_table(source)
        return None
    if kind == "flow":
        from pydantic import ValidationError

        from arp.reporting.mermaid_flow import MermaidError

        if not isinstance(source, str):
            raise BlockInvalid("invalid block")
        try:
            return render("flow", source)
        except MermaidError as exc:
            raise BlockInvalid(str(exc)) from None
        except ValidationError as exc:
            raise BlockInvalid(exc.errors()[0]["msg"]) from None
    if not isinstance(source, dict):
        raise BlockInvalid("invalid block")
    if (path := _outside(source, "")) is not None:
        raise BlockInvalid(f"chart may not load from outside: {path}")
    if _too_many_rows(source):
        raise BlockInvalid("chart exceeds 5000 data rows")
    try:
        return render_chart(source)
    except RenderFailed as exc:
        raise BlockInvalid(f"chart does not render: {exc}") from None
