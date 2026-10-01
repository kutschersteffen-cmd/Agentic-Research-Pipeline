"""A framework from a list of indicators: one row per indicator, no
company data. The list fixes what Derive would otherwise guess from the
values -- groups, weights, directions -- so nothing here reads a company.
Format: docs/decision-studio/indicator-list.md."""

from __future__ import annotations

import re

from arp.decision.parsing import is_blank, to_bool, to_number
from arp.schemas.decision import IndicatorSpec

_SCALE = re.compile(r"^\s*(-?\d+)\s*[-–]\s*(-?\d+)\s*$")


def parse_indicator_list(matrix: list[list[str]]) -> list[IndicatorSpec]:
    """Header row first; column names are case-insensitive. Raises
    ValueError naming the 1-based data row of the first problem."""
    if not matrix:
        raise ValueError("The indicator list is empty.")
    header = [h.strip() for h in matrix[0]]
    keys = [h.lower() for h in header]
    for required in ("id", "name", "group"):
        if required not in keys:
            raise ValueError(f"The indicator list needs a '{required}' column.")
    specs: list[IndicatorSpec] = []
    seen: set[str] = set()
    data = [r for r in matrix[1:] if any(not is_blank(c) for c in r)]
    for n, raw in enumerate(data, start=1):
        row = {k: (raw[i].strip() if i < len(raw) else "") for i, k in enumerate(keys)}

        def fail(message: str, n: int = n) -> ValueError:
            return ValueError(f"Indicator list row {n}: {message}")

        for required in ("id", "name", "group"):
            if not row.get(required):
                raise fail(f"'{required}' is blank")
        if row["id"] in seen:
            raise fail(f"indicator {row['id']} appears twice")
        seen.add(row["id"])
        fields: dict = {"id": row["id"], "name": row["name"], "group": row["group"]}
        for key in ("weight", "group_weight"):
            if row.get(key):
                value = to_number(row[key])
                if value is None or value < 0:
                    raise fail(f"'{key}' must be a number of 0 or more, got {row[key]!r}")
                fields[key] = value
        if row.get("scale"):
            m = _SCALE.match(row["scale"])
            if not m or int(m.group(1)) >= int(m.group(2)):
                raise fail(f"'scale' must look like 0-3, got {row['scale']!r}")
            fields["scale_min"], fields["scale_max"] = int(m.group(1)), int(m.group(2))
        if row.get("direction"):
            if row["direction"].lower() not in ("higher", "lower"):
                raise fail(f"'direction' must be higher or lower, got {row['direction']!r}")
            fields["direction"] = row["direction"].lower()
        if row.get("critical"):
            fields["critical"] = to_bool(row["critical"]) == 1
        if row.get("question"):
            fields["question"] = row["question"]
        kind = (row.get("kind") or "indicator").lower()
        if kind not in ("indicator", "event"):
            raise fail(f"'kind' must be indicator or event, got {row['kind']!r}")
        fields["kind"] = kind
        if kind == "event":
            outlook = (row.get("outlook") or "").capitalize()
            if outlook not in ("Negative", "Watch"):
                raise fail("an event needs 'outlook' Negative or Watch")
            fields["outlook"] = outlook
        views = {}
        for i, key in enumerate(keys):
            if key.startswith("view_") and row.get(key):
                value = to_number(row[key])
                if value is None or value < 0:
                    raise fail(f"'{header[i]}' must be a number of 0 or more, got {row[key]!r}")
                views[header[i][len("view_") :]] = value
        fields["views"] = views
        specs.append(IndicatorSpec(**fields))
    scales = {(s.scale_min, s.scale_max) for s in specs if s.kind == "indicator"}
    if len(scales) > 1:
        raise ValueError(f"All indicators must share one scale; found {', '.join(f'{a}-{b}' for a, b in sorted(scales))}.")
    return specs
