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
from arp.transition_barrier.render import rubric
from arp.transition_barrier.rule_book import RuleBookError, load_rule_book
from arp.transition_barrier.validation import read_and_validate


def data_dir() -> Path:
    return get_settings().transition_barrier_data_dir


def check_rule_book(directory: Path | None = None) -> None:
    """Raise RuleBookNotFound, or RuleBookError naming the first error, unless the rule book is valid.

    Validates the raw JSON before any model is built, so a bad file reads as an error line.
    """
    _, _, errors = read_and_validate(directory or data_dir())
    if errors:
        raise RuleBookError(errors[0])


@lru_cache
def load_criteria(path: Path | None = None) -> list[BarrierCriterion]:
    """The 35 transition-barrier criteria: 9 hard-to-abate sectors x the three
    constraint pillars (Technology / Regulation / Demand & Economics), each with
    a measurable metric and an H/M/L rubric rendered from the rule book
    (rule_book.json), which also supplies rationale, actions, facts and params.

    Derived from the working research tool (docs/transition_barrier/
    Transition_Barrier_Assessment.xlsx, "Criteria Reference" sheet), verified
    against each primary publisher in August 2026. This file is authoritative:
    source_registry.json is a derived view over its primary_sources[] entries.
    """
    directory = path.parent if path else data_dir()
    check_rule_book(directory)
    rule_book, _ = load_rule_book(directory)
    rows = json.loads((path or directory / "criteria_schema.json").read_text())["criteria"]
    out = []
    for row in rows:
        rules = rule_book.criteria[row["code"]]
        out.append(
            BarrierCriterion.model_validate(
                {
                    **row,
                    "rating_rubric": rubric(rules),
                    "rationale": rules.rationale,
                    "actions": rules.actions,
                    "facts": [f.model_dump(mode="json") for f in rules.facts],
                    "params": [p.model_dump(mode="json") for p in rules.params],
                    "rule_book_version": rule_book.version,
                }
            )
        )
    return out


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
    """The 89 deduplicated sources behind the matrix.

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
