"""The agent draws a block (spec agent-board, "Drawing (D3, D4)"): prompt, one retry, and the number check."""

from __future__ import annotations

import asyncio
import json
import math
import re
from typing import Any, Literal

from pydantic import BaseModel

from arp.agent_board.checks import BlockInvalid, checked_view, storable
from arp.llm.base import LLMClient

MAX_THREAD_BYTES = 20000

SYSTEM = """You draw one block on a research board, as JSON {kind, title, source}. Kinds and their source:
- "note": a Markdown string (headings, bold, italics, lists, inline code). No HTML. At most 20000 characters.
- "table": {"columns": [string], "rows": [[string | number | null]]}, 1 to 20 columns, at most 200 rows, every row as
  long as columns. Put numbers in cells as JSON numbers, not strings. Live form: {"live": pointer, "columns": [string]}
  with no "rows": each object of the pointed-to list is a row, one cell per column read from the key of that name.
- "chart": a Vega-Lite object with its data inline in data.values (at most 5000 rows). Never use url, href or loader
  keys, and never an image mark. Leave out config: the house theme is applied for you. Live form: a top-level
  "live": pointer instead of "data"; the pointed-to list of objects becomes data.values.
- "diagram": a Mermaid string, at most 8000 characters, whose first line starts with one of flowchart, mindmap,
  timeline, sequenceDiagram or quadrantChart. Pick the diagram type that makes the request clearest. No %%{ config,
  no click, style, classDef or linkStyle lines, no HTML tags, no links (http://, https://, javascript:). In a
  flowchart, end each node with :::GroupName to group the nodes, using 1 to 4 short CamelCase group names that help
  the reader (who acts, phase, theme), and mark at most one key step with a line "class <id> emphasis"; class lines
  are only for emphasis. Set no colours and no config: the house colours are applied for you. Labels at most 5 words.
- "tiles": {"tiles": [{"label": string, "value": number, "format": "number" | "percent", "change": number,
  "note": string}]}, 1 to 4 key numbers. label 1 to 40 characters, note at most 80; format, change and note are
  optional; "percent" means 0.31 shows as 31.0%. Live form of a value: {"live": pointer} to one number.
- "checklist": {"items": [{"text": string, "done": false}]}, 1 to 50 items, text 1 to 200 characters.
A pointer is a JSON Pointer into the thread data, starting with /, such as /steps/0/result/weights. When the numbers
come straight from one list or one number in the thread data, use a live pointer instead of copying them.
The title is 1 to 120 characters.
Use only numbers that appear in the thread data, exactly as they appear there; do not compute totals, shares or
percentages. Never put a URL in a chart. Reply in the language of the request."""


class BoardBlockDraft(BaseModel):
    kind: Literal["note", "table", "chart", "flow", "diagram", "tiles", "checklist"]
    title: str
    source: Any


class DrawRefused(Exception):
    """`str()` is the check message of the second draft."""


def compact(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def cut(text: str) -> str:
    """Over 20 000 bytes as UTF-8: the longest prefix of whole characters that fits, plus the truncation line."""
    data = text.encode("utf-8")
    if len(data) <= MAX_THREAD_BYTES:
        return text
    return data[:MAX_THREAD_BYTES].decode("utf-8", errors="ignore") + f"\n(thread data truncated at {MAX_THREAD_BYTES} bytes)"


def build_prompt(request: str, thread_data: dict, current: dict | None = None, refused: str | None = None) -> str:
    parts = [f"Request: {request}"]
    if current is not None:
        parts.append("Current block: " + compact({k: current[k] for k in ("kind", "title", "source")}))
    parts.append("Thread data:\n" + cut(compact(thread_data)))
    if refused is not None:
        parts.append(f"Your last answer was refused: {refused}")
    return "\n\n".join(parts)


def _json_numbers(node: Any, out: list) -> None:
    if isinstance(node, bool):
        return
    if isinstance(node, int | float):
        if math.isfinite(node):  # 1e999 in a JSON string parses to inf: not a number Postgres can store
            out.append(node)
    elif isinstance(node, dict):
        for v in node.values():
            _json_numbers(v, out)
    elif isinstance(node, list):
        for v in node:
            _json_numbers(v, out)


def _values_numbers(values: Any, out: list) -> None:
    """Numbers of an inline `values`: JSON numbers, also inside a JSON array string; in a CSV or TSV string, every cell
    that `float()` parses to a finite value (the spec's CSV rule), so string data cannot hide a number from D4."""
    if not isinstance(values, str):
        _json_numbers(values, out)
        return
    try:
        _json_numbers(json.loads(values), out)
        return
    except ValueError:
        pass
    for line in values.splitlines():
        for cell in re.split(r"[,\t]", line):
            try:
                n = float(cell)
            except ValueError:
                continue
            if math.isfinite(n):
                out.append(n)


def _chart_numbers(node: Any, out: list) -> None:
    """Numbers inside every `data.values` and every `datasets` entry, at any depth."""
    if isinstance(node, dict):
        data = node.get("data")
        if isinstance(data, dict):
            _values_numbers(data.get("values"), out)
        if isinstance(node.get("datasets"), dict):
            for v in node["datasets"].values():
                _values_numbers(v, out)
        for v in node.values():
            _chart_numbers(v, out)
    elif isinstance(node, list):
        for v in node:
            _chart_numbers(v, out)


def unverified(kind: str, source: Any, thread_data: Any) -> list:
    """D4: the sorted distinct numbers of a chart, table or tiles that no thread number matches to 2 decimals. Numbers
    read through a live pointer are thread data and never counted."""
    if kind not in ("chart", "table", "tiles"):
        return []
    found: list = []
    if kind == "chart":
        _chart_numbers(source, found)
    elif kind == "table":
        _json_numbers(source.get("rows"), found)
    else:
        for t in source["tiles"]:
            _json_numbers([v for v in (t.get("value"), t.get("change")) if not isinstance(v, dict)], found)
    known: list = []
    _json_numbers(thread_data, known)
    rounded = {round(c, 2) for c in known}
    return sorted({n for n in found if round(n, 2) not in rounded})


async def draw(llm: LLMClient, request: str, thread_data: dict, current: dict | None = None
               ) -> tuple[BoardBlockDraft, dict, list]:
    """A checked draft, its view (`rendered`, `live`, `live_error`, `live_step`) and `unverified`. A refused draft, or
    one with a `live_error`, gets one retry; a second refusal raises `DrawRefused`. Model call errors propagate."""
    refused = None
    for _ in range(2):
        draft, _usage = await llm.complete_structured(
            system=SYSTEM, prompt=build_prompt(request, thread_data, current, refused), output_model=BoardBlockDraft)
        try:
            if not storable([draft.title, draft.source]):  # checked like a person's body (NUL, surrogates, NaN)
                raise BlockInvalid("invalid block")
            shown = await asyncio.to_thread(checked_view, draft.kind, draft.title, draft.source, thread_data)
            if shown["live_error"] is not None:
                raise BlockInvalid(shown["live_error"])
        except BlockInvalid as exc:
            refused = str(exc)
            continue
        return draft, shown, unverified(draft.kind, draft.source, thread_data)
    raise DrawRefused(refused)
