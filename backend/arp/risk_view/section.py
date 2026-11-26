"""Find a company's risk section in plain text (theme-risk-mode A1): shared by the risk view and risk mode."""

from __future__ import annotations

import json
import re
from pathlib import Path

START = re.compile(r"^(Item 1A\b|(D\.\s*)?Risk Factors$|Risk and opportunity report|Principal risks|Risk report|Risikobericht)", re.I)
STOP = re.compile(r"^Item (1B|1C|2|4)\b", re.I)
STOPS = [s.lower() for s in json.loads((Path(__file__).parent / "data" / "section_stops.json").read_text())]


def clean(line: str) -> str:
    return line.strip().strip("#*").strip()


def is_start(line: str) -> bool:
    return bool(START.match(clean(line)))


def _is_stop(line: str) -> bool:
    s = clean(line)
    return bool(STOP.match(s)) or s.lower().startswith(tuple(STOPS))


def find_risk_section(text: str) -> tuple[int, int] | None:
    """Char offsets (end exclusive) of the longest span from a start line to the first later stop line."""
    lines, offset = [], 0
    for line in text.split("\n"):
        lines.append((offset, line))
        offset += len(line) + 1
    best = None
    for i, (start, line) in enumerate(lines):
        if not is_start(line):
            continue
        end = next((o for o, later in lines[i + 1:] if _is_stop(later)), len(text))
        if best is None or end - start > best[1] - best[0]:
            best = (start, end)
    return best
