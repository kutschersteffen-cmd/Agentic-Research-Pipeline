from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from arp.config import get_settings
from arp.schemas.transition_barrier import (
    BarrierCriterion,
    BarrierScore,
    Pillar,
    Region,
    RegistrySource,
)


def data_dir() -> Path:
    return get_settings().transition_barrier_data_dir


@lru_cache
def load_criteria(path: Path | None = None) -> list[BarrierCriterion]:
    """The 35 transition-barrier criteria: 9 hard-to-abate sectors x the three
    constraint pillars (Technology / Regulation / Demand & Economics), each with
    a measurable metric and an explicit H/M/L rubric.

    Derived from the working research tool (docs/transition_barrier/
    Transition_Barrier_Assessment.xlsx, "Criteria Reference" sheet), verified
    against each primary publisher in August 2026. This file is authoritative:
    source_registry.json is a derived view over its primary_sources[] entries.
    """
    rows = json.loads((path or data_dir() / "criteria_schema.json").read_text())["criteria"]
    return [BarrierCriterion.model_validate(row) for row in rows]


@lru_cache
def load_scores(path: Path | None = None) -> list[BarrierScore]:
    """The 105 matrix cells -- each of the 35 criteria rated H/M/L for the
    European Union, United States and China, with evidence and a confidence
    tier. Note the JSON array key is `scores`, not `ratings`.
    """
    rows = json.loads((path or data_dir() / "assessment_scores.json").read_text())["scores"]
    return [BarrierScore.model_validate(row) for row in rows]


@lru_cache
def load_source_registry(path: Path | None = None) -> list[RegistrySource]:
    """The 86 deduplicated sources behind the matrix.

    Unlike the other two files, `sources` here is a JSON *object* keyed by an
    internal identifier rather than an array, so the key is folded into each
    record as `key` to keep the returned shape consistent.
    """
    raw = json.loads((path or data_dir() / "source_registry.json").read_text())["sources"]
    return [RegistrySource.model_validate({"key": key, **row}) for key, row in raw.items()]


def reset_caches() -> None:
    """Drop the loader caches; needed after the data directory setting changes."""
    for loader in (load_criteria, load_scores, load_source_registry):
        loader.cache_clear()


def sources_for_criterion(code: str) -> list[RegistrySource]:
    """Resolve the criterion -> source join. criteria_schema.json is
    authoritative for *which* sources back a criterion; the registry is used
    only to return the deduplicated record for each.
    """
    return [s for s in load_source_registry() if code in s.used_by_criteria]


def filter_scores(
    *,
    sector: str | None = None,
    region: Region | None = None,
    pillar: Pillar | None = None,
    rating: str | None = None,
    code: str | None = None,
) -> list[BarrierScore]:
    """Filter the 105 cells. Every argument is optional and ANDed together."""
    rows = load_scores()
    if sector:
        rows = [r for r in rows if r.sector == sector]
    if region:
        rows = [r for r in rows if r.region is region]
    if pillar:
        rows = [r for r in rows if r.category is pillar]
    if rating:
        rows = [r for r in rows if r.rating.value == rating]
    if code:
        rows = [r for r in rows if r.code == code]
    return rows


def build_matrix() -> dict[str, dict[str, BarrierScore]]:
    """The 35x3 grid as {criterion_code: {region: score}} -- the shape the
    frontend heatmap consumes.
    """
    grid: dict[str, dict[str, BarrierScore]] = {}
    for score in load_scores():
        grid.setdefault(score.code, {})[score.region.value] = score
    return grid


def rating_distribution(region: Region | None = None) -> dict[str, int]:
    """H/M/L counts, optionally for one region. Always returns all three keys so
    a zero count is visible rather than missing.
    """
    counts = {"H": 0, "M": 0, "L": 0}
    for score in load_scores():
        if region is None or score.region is region:
            counts[score.rating.value] += 1
    return counts


def sectors() -> list[str]:
    """The 9 sectors, in the order they appear in the criteria schema."""
    seen: list[str] = []
    for criterion in load_criteria():
        if criterion.sector not in seen:
            seen.append(criterion.sector)
    return seen
