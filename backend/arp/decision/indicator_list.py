"""A framework from a list of indicators: one row per indicator, no
company data. The list fixes what Derive would otherwise guess from the
values -- groups, weights, directions -- so nothing here reads a company.
Format: docs/decision-studio/indicator-list.md."""

from __future__ import annotations

import re

from arp.decision.credibility import apply_preset, level_expr
from arp.decision.parsing import is_blank, to_bool, to_number
from arp.decision.roles import slug
from arp.schemas.decision import AuditEntry, Dimension, IndicatorSpec, LevelCriterion, LevelRule, MechanismConfig

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


def build_framework(specs: list[IndicatorSpec], *, name: str) -> tuple[MechanismConfig, list[AuditEntry]]:
    """A levels-mode draft: the score is the level (flipped for lower is
    better), one cluster per group. Tiers stay `Tier 1`..`Tier 4` on evenly
    spaced cut-points until the analyst names them."""
    indicators = [s for s in specs if s.kind == "indicator"]
    if not indicators:
        raise ValueError("The indicator list has no indicators, only events.")
    lo, hi = indicators[0].scale_min, indicators[0].scale_max
    groups: dict[str, Dimension] = {}
    weighted: set[str] = set()  # groups whose first non-blank group_weight is taken
    for s in indicators:
        if s.group not in groups:
            groups[s.group] = Dimension(id=f"g{len(groups) + 1}", name=s.group)
        if s.group_weight is not None and s.group not in weighted:
            groups[s.group].weight = s.group_weight
            weighted.add(s.group)
    criteria = []
    for s in indicators:
        key = slug(s.id)
        if not re.fullmatch(r"[a-z_]\w*", key):
            raise ValueError(f"Indicator id {s.id!r} must start with a letter to be read in a rule.")
        value = level_expr(s)
        criteria.append(
            LevelCriterion(
                id=s.id,
                name=s.name,
                dimension_id=groups[s.group].id,
                weight=s.weight,
                rules=[LevelRule(level=k, when=f"{value} >= {k}") for k in range(hi, lo, -1)],
                otherwise=lo,
                otherwise_on_blank=True,
                hint=s.question or "",
            )
        )
    config = MechanismConfig(
        name=name,
        mode="levels",
        level_min=lo,
        level_max=hi,
        level_criteria=criteria,
        dimensions=list(groups.values()),
        label_column="Company",
        source_columns=[s.id for s in specs],
        min_coverage_pct=0,
        cut_mode="absolute",
        pinned_cuts=[lo + (hi - lo) * k / 4 for k in (3, 2, 1)],
    )

    def entry(item: str, decision: str, why: str) -> AuditEntry:
        return AuditEntry(stage="Indicator list", item=item, decision=decision, why=why, origin="derived")

    audit = [
        entry("Scale", f"{lo}-{hi}", "Every indicator's score is its level; lower-is-better indicators are flipped."),
        entry("Blank scores", f"count as {lo}", "A missing score is the bottom of the scale (0 = absent)."),
        entry("Clusters", ", ".join(f"{d.name} ×{d.weight:g}" for d in config.dimensions), "One cluster per group; group_weight sets its weight, else 1."),
        entry("Cut-points", ", ".join(f"{c:g}" for c in config.pinned_cuts), "Evenly spaced on the scale until the tiers are named."),
    ]
    questions = sorted({s.question for s in indicators if s.question})
    if len(questions) == 5:
        config = apply_preset(config, specs, audit)
    elif questions:
        audit.append(entry("Credibility preset", "skipped", f"The list names {len(questions)} questions; the preset needs exactly five questions."))
    return config, audit
