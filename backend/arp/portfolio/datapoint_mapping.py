from __future__ import annotations

from arp.schemas.portfolio import DataPointObservation
from arp.storage.portfolio_store import PortfolioStore

_SOURCE_PRIORITY = {"internal_api": 0, "extracted": 1, "catalogue": 2, "estimated_proxy": 3}
"""A disclosed/API-sourced number is never second-guessed by an inferred
one -- same cascade philosophy as
`research/revenue_exposure/resolver.py`'s catalogue -> extraction ->
qualitative priority, applied here to (company, field) observation
history instead of a single run's in-memory results."""


def resolve_field_value(store: PortfolioStore, company_id: str, field_id: str, as_of: str | None = None) -> DataPointObservation | None:
    """Resolves one company's value for one field as of a date: the latest
    observation from the highest-priority source that has *any*
    observation known by that date. A more recent low-priority observation
    never wins over an older high-priority one.
    """
    observations = store.load_observations(company_id, field_id)
    if as_of:
        observations = [o for o in observations if o.observed_at[:10] <= as_of]
    if not observations:
        return None

    latest_by_source: dict[str, DataPointObservation] = {}
    for obs in observations:
        current = latest_by_source.get(obs.source)
        if current is None or obs.observed_at > current.observed_at:
            latest_by_source[obs.source] = obs

    best_source = min(latest_by_source, key=lambda s: _SOURCE_PRIORITY.get(s, 99))
    return latest_by_source[best_source]


def resolve_field_values_for_universe(
    store: PortfolioStore, company_ids: list[str], field_id: str, as_of: str | None = None
) -> dict[str, float]:
    """Bulk resolution feeding `aggregation.aggregate`'s `data_point_values`.
    Only companies with a resolved *numeric* value are included; everyone
    else is simply absent from the dict, so the aggregation engine's own
    coverage/`unresolved_market_value_eur` accounting reports them as
    missing rather than this function silently defaulting them to zero.
    """
    values: dict[str, float] = {}
    for company_id in company_ids:
        obs = resolve_field_value(store, company_id, field_id, as_of)
        if obs is not None and isinstance(obs.value, (int, float)) and not isinstance(obs.value, bool):
            values[company_id] = float(obs.value)
    return values


def coverage_summary(store: PortfolioStore, company_ids: list[str], field_id: str, as_of: str | None = None) -> dict[str, int]:
    """Counts of companies resolved per source, plus a `missing` bucket --
    the raw material for the internal-API / extracted / estimated / missing
    breakdown `climate/metrics.py` reports alongside every climate number.
    """
    counts: dict[str, int] = {source: 0 for source in _SOURCE_PRIORITY}
    counts["missing"] = 0
    for company_id in company_ids:
        obs = resolve_field_value(store, company_id, field_id, as_of)
        if obs is None:
            counts["missing"] += 1
        else:
            counts[obs.source] = counts.get(obs.source, 0) + 1
    return counts
