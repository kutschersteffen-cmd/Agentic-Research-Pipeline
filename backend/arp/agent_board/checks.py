"""Block checks and rendering (spec agent-board, "Block sources and validation", "Rendering" and Phase 2).

`checked_view` raises `BlockInvalid` with the spec's message for the first failing check, else returns the block's
`rendered`, `live`, `live_error` and `live_step`, so a write renders a chart once. `view` gives the same for a stored
block on a read.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys
import threading
from collections import OrderedDict
from typing import Any

from arp.agent_board import live as lv

KINDS = ("note", "table", "chart", "flow", "diagram", "tiles", "checklist")
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
    if not isinstance(source, dict) or not isinstance(source.get("columns"), list):
        raise BlockInvalid("invalid block")
    if ("rows" in source) == ("live" in source) or ("rows" in source and not isinstance(source["rows"], list)):
        raise BlockInvalid("invalid block")  # rows or live, never both and never neither
    cols = source["columns"]
    if not all(isinstance(c, str) for c in cols):
        raise BlockInvalid("invalid block")
    if "live" in source:
        _pointer(source["live"])
    if not 1 <= len(cols) <= 20:
        raise BlockInvalid("table must have 1 to 20 columns")
    if "live" in source:
        return
    rows = source["rows"]
    if len(rows) > 200:
        raise BlockInvalid("table exceeds 200 rows")
    for i, row in enumerate(rows, start=1):
        if not isinstance(row, list) or not all(c is None or isinstance(c, str) or _is_number(c) for c in row):
            raise BlockInvalid("invalid block")
        if len(row) != len(cols):
            raise BlockInvalid(f"row {i} has {len(row)} cells, expected {len(cols)}")


def _pointer(p: Any) -> str:
    try:
        return lv.check_pointer(p)
    except lv.PointerInvalid as exc:
        raise BlockInvalid(str(exc)) from None


DIAGRAM_TYPES = ("flowchart", "mindmap", "timeline", "sequenceDiagram", "quadrantChart")
_DIAGRAM_TYPE_MSG = "unsupported diagram type: {}; use flowchart, mindmap, timeline, sequenceDiagram or quadrantChart"
_REFUSED_STATEMENTS = ("click", "style", "classdef", "linkstyle", "link", "links", "href")
_GROUP = re.compile(r":::([A-Za-z][A-Za-z0-9_]*)")


def _check_diagram(source: Any) -> None:
    """Phase 2 `diagram` (D6, D7): the checks in the spec's order."""
    if not isinstance(source, str):
        raise BlockInvalid("invalid block")
    if len(source) > 8000:
        raise BlockInvalid("diagram exceeds 8000 characters")
    lines = source.splitlines()
    first = next((ln for ln in lines if ln.strip() and not ln.strip().startswith("%%")), "")
    word = first.split()[0] if first.split() else ""
    if word not in DIAGRAM_TYPES:
        raise BlockInvalid(_DIAGRAM_TYPE_MSG.format(word))
    if "%%{" in source:
        raise BlockInvalid("diagram may not set its own config")
    statements = [st.split() for ln in lines for st in ln.split(";")]  # Amendment 1b: `;` ends a statement too
    for words in statements:
        if words and words[0].lower() in _REFUSED_STATEMENTS:
            raise BlockInvalid(f"diagram may not use {words[0]} lines")
    for words in statements:
        if words and words[0] == "class" and words[-1] != "emphasis":
            raise BlockInvalid("diagram may only use class lines for emphasis")
    if re.search(r"<[A-Za-z/!]", source):
        raise BlockInvalid("diagram may not contain HTML")
    if "@{" in source:
        raise BlockInvalid("diagram may not use shape options")
    low = source.lower()
    if any(x in low for x in ("javascript:", "http:", "https:", "//", "\\\\", ":\\")):
        raise BlockInvalid("diagram may not load from outside")
    groups = {g for g in _GROUP.findall(source) if g != "emphasis"}
    if len(groups) > 4:
        raise BlockInvalid(f"diagram has {len(groups)} colour groups; at most 4")


_TILE_KEYS = {"label", "value", "format", "change", "note"}


def _check_tiles(source: Any) -> None:
    if not isinstance(source, dict) or set(source) != {"tiles"} or not isinstance(source["tiles"], list):
        raise BlockInvalid("invalid block")
    tiles = source["tiles"]
    for t in tiles:  # shape first: answers `invalid block` before any listed check
        if (not isinstance(t, dict) or not set(t) <= _TILE_KEYS or not isinstance(t.get("label"), str)
                or ("note" in t and not isinstance(t["note"], str))):
            raise BlockInvalid("invalid block")
    if not 1 <= len(tiles) <= 4:
        raise BlockInvalid("tiles must have 1 to 4 tiles")
    for i, t in enumerate(tiles, start=1):
        if not 1 <= len(t["label"].strip()) <= 40:
            raise BlockInvalid(f"tile {i}: label must be 1 to 40 characters")
        value = t.get("value")
        if isinstance(value, dict) and set(value) == {"live"}:
            _pointer(value["live"])
        elif not _is_number(value):
            raise BlockInvalid(f"tile {i}: value must be a number")
        if "change" in t and not _is_number(t["change"]):
            raise BlockInvalid(f"tile {i}: change must be a number")
        if len(t.get("note", "")) > 80:
            raise BlockInvalid(f"tile {i}: note exceeds 80 characters")
        if t.get("format", "number") not in ("number", "percent"):
            raise BlockInvalid(f"tile {i}: format must be number or percent")


def _check_checklist(source: Any) -> None:
    if not isinstance(source, dict) or set(source) != {"items"} or not isinstance(source["items"], list):
        raise BlockInvalid("invalid block")
    items = source["items"]
    for it in items:
        if not isinstance(it, dict) or not set(it) <= {"text", "done"} or not isinstance(it.get("text"), str):
            raise BlockInvalid("invalid block")
    if not 1 <= len(items) <= 50:
        raise BlockInvalid("checklist must have 1 to 50 items")
    for i, it in enumerate(items, start=1):
        if not 1 <= len(it["text"].strip()) <= 200:
            raise BlockInvalid(f"item {i}: text must be 1 to 200 characters")
        if not isinstance(it.get("done"), bool):
            raise BlockInvalid(f"item {i}: done must be true or false")


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
    """`rendered` of a stored block that holds no pointer: SVGs for a chart, the parsed `Flow` for a flow, the values
    of tiles, else null."""
    if kind == "tiles":
        return {"values": [t["value"] for t in source["tiles"]]}
    if kind == "chart":
        return render_chart(source)
    if kind == "flow":
        from arp.reporting.mermaid_flow import parse_mermaid

        return parse_mermaid(source).model_dump(mode="json")
    return None


def is_live(kind: str, source: Any) -> bool:
    """`live`: the source holds a pointer."""
    if kind in ("chart", "table"):
        return isinstance(source, dict) and "live" in source
    if kind == "tiles" and isinstance(source, dict) and isinstance(source.get("tiles"), list):
        return any(isinstance(t, dict) and isinstance(t.get("value"), dict) and "live" in t["value"]
                   for t in source["tiles"])
    return False


def _view(rendered: Any = None, live: bool = False, live_error: str | None = None,
          live_step: int | None = None) -> dict:
    return {"rendered": rendered, "live": live, "live_error": live_error, "live_step": live_step}


MAX_FAILED_RENDERS = 1000
_FAILED_RENDERS: OrderedDict[tuple, str] = OrderedDict()  # (block id, version, sha256 of data) -> live_error
_FAILED_LOCK = threading.Lock()


def _live_chart(source: dict, data: Any, key: tuple | None = None, strict: bool = False) -> dict:
    """A live chart resolved against the thread data. A render failure on a write (`strict`) is refused; on a read it
    is remembered per (block id, version, data hash) in `key`, so the same block and data never render twice."""
    p = source["live"]
    rows, error = lv.rows_of(p, data)
    step = lv.step_of(p, data)
    resolved = {k: v for k, v in source.items() if k != "live"}
    resolved["data"] = {"values": rows}
    try:
        too_many = _too_many_rows(resolved)
    except BlockInvalid as exc:
        if strict:
            raise
        return _view(None, True, error or str(exc), step)
    if too_many:
        return _view(None, True, error or "chart exceeds 5000 data rows", step)
    if key is not None:
        digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        key = (*key, digest)
        with _FAILED_LOCK:
            remembered = _FAILED_RENDERS.get(key)
        if remembered is not None:
            return _view(None, True, error or remembered, step)
    try:
        rendered = render_chart(resolved)
    except RenderFailed as exc:
        message = f"chart does not render: {exc}"
        if strict:
            raise BlockInvalid(message) from None
        if key is not None:
            with _FAILED_LOCK:
                _FAILED_RENDERS[key] = message
                while len(_FAILED_RENDERS) > MAX_FAILED_RENDERS:
                    _FAILED_RENDERS.popitem(last=False)
        return _view(None, True, error or message, step)
    return _view(rendered, True, error, step)


def _live_table(source: dict, data: Any) -> dict:
    p = source["live"]
    rows, error = lv.rows_of(p, data)
    if len(rows) > 200:
        rows, error = rows[:200], "live data exceeds 200 rows"
    out = [[lv.cell(r.get(c)) for c in source["columns"]] for r in rows]
    return _view({"rows": out}, True, error, lv.step_of(p, data))


def _tiles(source: dict, data: Any) -> dict:
    values, error, step, live = [], None, None, False
    for t in source["tiles"]:
        value = t["value"]
        if isinstance(value, dict):
            p = value["live"]
            n, err = lv.number_of(p, data)
            if not live:
                step, live = lv.step_of(p, data), True
            error = error or err
            values.append(n)
        else:
            values.append(value)
    return _view({"values": values}, live, error, step)


def view(kind: str, source: Any, data: Any = None, key: tuple | None = None) -> dict:
    """`rendered`, `live`, `live_error` and `live_step` of a stored block, resolved against the thread data. A
    block that no longer draws answers `rendered: null`, so it cannot hide the rest of the board. `key`, the block's
    (id, version), lets a live chart remember a failed render (Amendment 1b)."""
    if kind == "chart" and is_live(kind, source):
        return _live_chart(source, data, key)
    if kind == "table" and is_live(kind, source):
        return _live_table(source, data)
    if kind == "tiles" and is_live(kind, source):
        return _tiles(source, data)
    return _view(render(kind, source))


def checked_view(kind: Any, title: Any, source: Any, data: Any = None) -> dict:
    """Raises `BlockInvalid` for the first failing check; returns the block's view (see `view`)."""
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
        return _view()
    if kind == "table":
        _check_table(source)
        return view(kind, source, data)
    if kind == "diagram":
        _check_diagram(source)
        return _view()
    if kind == "tiles":
        _check_tiles(source)
        return view(kind, source, data)
    if kind == "checklist":
        _check_checklist(source)
        return _view()
    if kind == "flow":
        from pydantic import ValidationError

        from arp.reporting.mermaid_flow import MermaidError

        if not isinstance(source, str):
            raise BlockInvalid("invalid block")
        try:
            return _view(render("flow", source))
        except MermaidError as exc:
            raise BlockInvalid(str(exc)) from None
        except ValidationError as exc:
            raise BlockInvalid(exc.errors()[0]["msg"]) from None
    if not isinstance(source, dict):
        raise BlockInvalid("invalid block")
    if "live" in source:
        if "data" in source:
            raise BlockInvalid("invalid block")
        _pointer(source["live"])
    if (path := _outside(source, "")) is not None:
        raise BlockInvalid(f"chart may not load from outside: {path}")
    if "live" in source:
        return _live_chart(source, data, strict=True)  # a data problem is `live_error`; a render failure is refused
    if _too_many_rows(source):
        raise BlockInvalid("chart exceeds 5000 data rows")
    try:
        return _view(render_chart(source))
    except RenderFailed as exc:
        raise BlockInvalid(f"chart does not render: {exc}") from None


def check_block(kind: Any, title: Any, source: Any, data: Any = None) -> Any:
    """Raises `BlockInvalid` for the first failing check; returns `rendered`."""
    return checked_view(kind, title, source, data)["rendered"]
