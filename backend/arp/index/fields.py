from __future__ import annotations

from arp.schemas.index import IndexCandidate, MissingPolicy

EPS = 1e-12

# Attributes every candidate has, exposed to rules under the same names as
# the free-form `metrics` map so a methodology can screen or tilt on them
# without the caller having to duplicate them into `metrics`.
DERIVED_METRICS: dict[str, str] = {
    "float_mcap": "Free-float market capitalisation in the index currency.",
    "price": "Close on the weight reference date, in the security's currency.",
    "shares_outstanding": "Shares outstanding.",
    "free_float_factor": "Free-float factor, 0-1.",
}


class DataQualityBlock(RuntimeError):
    """Raised when a rule meets a missing value under the `block` policy.

    This is the plan's "fail loud on data quality" principle: a run stops
    rather than defaulting silently. The documented override is to set the
    rule's `missing` policy to `fail` or `pass` deliberately -- which is
    recorded in the calibration and shows up in the review's exception
    list, rather than being a hidden edit to a data file.
    """


def metric_value(candidate: IndexCandidate, field: str) -> float | None:
    if field == "float_mcap":
        return candidate.float_mcap
    if field == "price":
        return candidate.price
    if field == "shares_outstanding":
        return candidate.shares_outstanding
    if field == "free_float_factor":
        return candidate.free_float_factor
    return candidate.metrics.get(field)


def flag_value(candidate: IndexCandidate, field: str) -> bool | None:
    return candidate.flags.get(field)


def category_value(candidate: IndexCandidate, field: str) -> str | None:
    if field == "sector":
        return candidate.sector
    if field == "country":
        return candidate.country
    return candidate.categories.get(field)


def resolve_missing(policy: MissingPolicy, *, rule_label: str, field: str, company_id: str) -> bool:
    """Returns whether a company with a missing value should be kept.

    `block` raises rather than returning, so a gap in the data can never be
    silently interpreted as either inclusion or exclusion.
    """
    if policy == "block":
        raise DataQualityBlock(f"{rule_label}: missing value for field {field!r} on {company_id!r}")
    return policy == "pass"


def available_fields(candidates: list[IndexCandidate]) -> dict[str, list[str]]:
    """Every field actually populated across the universe, so the UI can
    offer real choices rather than a free-text box that mistypes into a
    silently-missing field."""
    metrics: set[str] = set(DERIVED_METRICS)
    flags: set[str] = set()
    categories: set[str] = {"sector", "country"}
    for candidate in candidates:
        metrics.update(candidate.metrics)
        flags.update(candidate.flags)
        categories.update(candidate.categories)
    return {"metrics": sorted(metrics), "flags": sorted(flags), "categories": sorted(categories)}
