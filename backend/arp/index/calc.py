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
    seed_prices: dict[str, float] | None = None,
    seed_fx: dict[str, float] | None = None,
) -> list[IndexLevelPoint]:
    """Index levels across a price panel with the shares held fixed.

    `price_panel` is `{date: {company_id: price}}`. A constituent missing on
    a date carries its last observed price -- the standard stale-price
    treatment -- and the count of names actually priced that day is reported
    so a stale-heavy day is visible rather than hidden.

    `seed_prices` are the prices the shares were set from, normally the
    review's own constituent prices. They matter because a constituent with
    no price *yet* has no last price to carry: without a seed it would
    contribute nothing and the level would come out low -- wrong rather than
    stale, and indistinguishable from a genuine fall. Rather than let that
    publish, a name with neither a price nor a seed raises.
    """
    rounding = rounding or RoundingPolicy()
    points: list[IndexLevelPoint] = []
    last_price: dict[str, float] = dict(seed_prices or {})
    last_fx: dict[str, float] = dict(seed_fx or {})
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
            if company_id not in last_price:
                raise ValueError(
                    f"{company_id} has no price on {as_of} and none carried forward; "
                    "pass seed_prices (the review's constituent prices) so the series starts from a known level "
                    "instead of silently understating it"
                )
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

    `previous` must be the *drifted* pre-rebalance weights at the effective
    close, not the previous review's target weights. Use `drifted_weights`
    to build them: comparing target to target reports the trading the index
    would have needed had prices not moved, which is zero whenever the
    methodology is unchanged -- a number that looks reassuring and means
    nothing.
    """
    keys = sorted(set(previous) | set(current))
    return fsum(abs(current.get(k, 0.0) - previous.get(k, 0.0)) for k in keys) / 2.0


def drifted_weights(
    shares: dict[str, float],
    prices: dict[str, float],
    *,
    fallback_prices: dict[str, float] | None = None,
) -> dict[str, float]:
    """The weights a previous review's index actually carries today.

    Index shares are fixed between rebalances, so the weights move with
    price. Those drifted weights -- not the last set of targets -- are what
    the next rebalance trades away from.

    `prices` are today's, already in index currency. A holding that has left
    the universe (delisted, acquired) falls back to its last observed price,
    which is the standard stale treatment and keeps it in the turnover as
    the full sale it is. A holding with neither is dropped, and its weight
    shows up as turnover, which is also correct.
    """
    fallback_prices = fallback_prices or {}
    values: dict[str, float] = {}
    for company_id in sorted(shares):
        price = prices.get(company_id, fallback_prices.get(company_id))
        if price is None or price <= 0:
            continue
        values[company_id] = shares[company_id] * price
    total = fsum(values[k] for k in sorted(values))
    if total <= 0:
        return {}
    return {k: v / total for k, v in values.items()}
