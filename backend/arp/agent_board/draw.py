"""The agent draws a block (spec agent-board, "Drawing (D3, D4)"): prompt, one retry, and the number check."""

from __future__ import annotations

import asyncio
import json
import math
import re
from typing import Any, Literal

from pydantic import BaseModel

from arp.agent_board.checks import BlockInvalid, check_block, storable
from arp.llm.base import LLMClient

MAX_THREAD_BYTES = 20000

SYSTEM = """You draw one block on a research board, as JSON {kind, title, source}. Kinds and their source:
- "note": a Markdown string (headings, bold, italics, lists, inline code). No HTML. At most 20000 characters.
- "table": {"columns": [string], "rows": [[string | number | null]]}, 1 to 20 columns, at most 200 rows, every row as
  long as columns. Put numbers in cells as JSON numbers, not strings.
- "chart": a Vega-Lite object with its data inline in data.values (at most 5000 rows). Never use url, href or loader
  keys, and never an image mark. Leave out config: the house theme is applied for you.
- "flow": a Mermaid flowchart string. Start with "flowchart LR" or "flowchart TB". Steps are id[Label], id(Label) or
  id{Question}; arrows are a --> b or a -->|label| b. 2 to 12 steps, at most 20 arrows, step labels at most 5 words,
  arrow labels at most 3 words. No subgraph, style, linkStyle or click lines; no step pointing to itself.
The title is 1 to 120 characters.
Use only numbers that appear in the thread data, exactly as they appear there; do not compute totals, shares or
percentages. Never put a URL in a chart. Reply in the language of the request."""


class BoardBlockDraft(BaseModel):
    kind: Literal["note", "table", "chart", "flow"]
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
    """D4: the sorted distinct numbers of a chart or table that no thread number matches to 2 decimals."""
    if kind not in ("chart", "table"):
        return []
    found: list = []
    if kind == "chart":
        _chart_numbers(source, found)
    else:
        _json_numbers(source.get("rows"), found)
    known: list = []
    _json_numbers(thread_data, known)
    rounded = {round(c, 2) for c in known}
    return sorted({n for n in found if round(n, 2) not in rounded})


async def draw(llm: LLMClient, request: str, thread_data: dict, current: dict | None = None
               ) -> tuple[BoardBlockDraft, Any, list]:
    """A checked draft, its `rendered` and `unverified`. A refused draft gets one retry; a second refusal raises
    `DrawRefused`. Model call errors propagate."""
    refused = None
    for _ in range(2):
        draft, _usage = await llm.complete_structured(
            system=SYSTEM, prompt=build_prompt(request, thread_data, current, refused), output_model=BoardBlockDraft)
        try:
            if not storable([draft.title, draft.source]):  # checked like a person's body (NUL, surrogates, NaN)
                raise BlockInvalid("invalid block")
            rendered = await asyncio.to_thread(check_block, draft.kind, draft.title, draft.source)
        except BlockInvalid as exc:
            refused = str(exc)
            continue
        return draft, rendered, unverified(draft.kind, draft.source, thread_data)
    raise DrawRefused(refused)
