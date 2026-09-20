from __future__ import annotations

from math import fsum

from arp.schemas.index import IndexCandidate, IndexLevelPoint, RoundingPolicy


def index_shares(
    weights: dict[str, float],
    candidates: list[IndexCandidate],
    *,
    index_market_cap: float,
    rounding: RoundingPolicy,
) -> dict[str, float]:
    """Converts target weights into index shares at the effective close.

    Index shares are what make an index *continuous*: they are fixed
    between rebalances, so weights drift with price instead of being
    silently recomputed every day (which would be a daily-rebalanced
    portfolio, not an index).

    `index_market_cap` is the level times the divisor -- the capitalisation
    the index is being reconstituted at. Shares are rounded here, and the
    divisor is derived afterwards from the *rounded* shares, so the
    published shares exactly reproduce the published level.
    """
    by_id = {c.company_id: c for c in candidates}
    shares: dict[str, float] = {}
    for company_id in sorted(weights):
        candidate = by_id[company_id]
        raw = weights[company_id] * index_market_cap / (candidate.price * candidate.fx_rate)
        shares[company_id] = round(raw, rounding.shares_decimals)
    return shares


def market_cap(shares: dict[str, float], candidates: list[IndexCandidate]) -> float:
    by_id = {c.company_id: c for c in candidates}
    keys = sorted(k for k in shares if k in by_id)
    return fsum(shares[k] * by_id[k].price * by_id[k].fx_rate for k in keys)


def divisor_for_level(total_market_cap: float, level: float) -> float:
    """`D = MC / I`. At the base date this sets the divisor from the chosen
    base level; at every later event it is the identity that keeps the level
    continuous."""
    if level <= 0:
        raise ValueError("index level must be positive")
    return total_market_cap / level


def adjust_divisor(divisor_before: float, market_cap_before: float, market_cap_after: float) -> float:
    """`D_after = D_before x (MC_after / MC_before)`.

    Any event that changes market capitalisation without a corresponding
    investor return -- a rebalance, a share-count change, a special dividend
    -- must leave the index level unchanged. This single identity is the
    whole divisor engine; the corporate-action table only decides which
    events qualify.
    """
    if market_cap_before <= 0:
        raise ValueError("market cap before an adjustment must be positive")
    return divisor_before * (market_cap_after / market_cap_before)


def level_series(
    shares: dict[str, float],
    price_panel: dict[str, dict[str, float]],
    *,
    divisor: float,
    fx_panel: dict[str, dict[str, float]] | None = None,
    rounding: RoundingPolicy | None = None,
) -> list[IndexLevelPoint]:
    """Index levels across a price panel with the shares held fixed.

    `price_panel` is `{date: {company_id: price}}`. A constituent missing on
    a date carries its last observed price -- the standard stale-price
    treatment -- and the count of names actually priced that day is reported
    so a stale-heavy day is visible rather than hidden.
    """
    rounding = rounding or RoundingPolicy()
    points: list[IndexLevelPoint] = []
    last_price: dict[str, float] = {}
    last_fx: dict[str, float] = {}
    for as_of in sorted(price_panel):
        prices = price_panel[as_of]
        fx_rates = (fx_panel or {}).get(as_of, {})
        priced = 0
        total = 0.0
        for company_id in sorted(shares):
            price = prices.get(company_id)
            if price is not None:
                last_price[company_id] = price
                priced += 1
            fx = fx_rates.get(company_id)
            if fx is not None:
                last_fx[company_id] = fx
            if company_id in last_price:
                total += shares[company_id] * last_price[company_id] * last_fx.get(company_id, 1.0)
        points.append(
            IndexLevelPoint(
                date=as_of,
                level=round(total / divisor, rounding.level_decimals),
                divisor=divisor,
                market_cap=total,
                constituents_priced=priced,
            )
        )
    return points


def one_way_turnover(previous: dict[str, float], current: dict[str, float]) -> float:
    """Half the sum of absolute weight changes.

    Note the caller's responsibility: `previous` should be the *drifted*
    pre-rebalance weights at the effective close, not the previous review's
    target weights, or the number understates real trading.
    """
    keys = sorted(set(previous) | set(current))
    return fsum(abs(current.get(k, 0.0) - previous.get(k, 0.0)) for k in keys) / 2.0
