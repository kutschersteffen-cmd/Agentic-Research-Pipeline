from __future__ import annotations

from arp.schemas.taxonomy_sources import HoldingRow, HoldingsOverlapResult


def compute_holdings_overlap(fund_holdings: dict[str, list[HoldingRow]]) -> HoldingsOverlapResult:
    """Deterministic overlap analysis across two or more funds' holdings.
    Pure set/weight computation -- no LLM involved, consistent with this
    system's preference for a non-LLM computation wherever one is possible
    (the indirect-exposure Leontief tier is the other example of this).

    `pairwise_overlap_pct['fund_a|fund_b']` is a weight-adjusted overlap:
    for each ticker held by both funds, the smaller of the two weights is
    counted (the portion of each fund that could theoretically be
    "the same position"), summed and expressed as a percentage of the
    smaller fund's total weight. Falls back to a plain ticker-count
    Jaccard-style ratio when weight data isn't available for a pair.
    """
    fund_names = list(fund_holdings.keys())
    tickers_by_fund: dict[str, dict[str, HoldingRow]] = {
        name: {row.ticker: row for row in rows} for name, rows in fund_holdings.items()
    }

    all_tickers: set[str] = set()
    for tickers in tickers_by_fund.values():
        all_tickers.update(tickers.keys())

    ticker_presence: dict[str, list[str]] = {
        ticker: [name for name, tickers in tickers_by_fund.items() if ticker in tickers] for ticker in sorted(all_tickers)
    }
    core_tickers = sorted(t for t, funds in ticker_presence.items() if len(funds) == len(fund_names))
    union_tickers = sorted(all_tickers)

    pairwise_overlap_pct: dict[str, float] = {}
    for i, fund_a in enumerate(fund_names):
        for fund_b in fund_names[i + 1 :]:
            pairwise_overlap_pct[f"{fund_a}|{fund_b}"] = _pairwise_overlap(tickers_by_fund[fund_a], tickers_by_fund[fund_b])

    return HoldingsOverlapResult(
        fund_names=fund_names,
        core_tickers=core_tickers,
        union_tickers=union_tickers,
        ticker_presence=ticker_presence,
        pairwise_overlap_pct=pairwise_overlap_pct,
    )


def _pairwise_overlap(a: dict[str, HoldingRow], b: dict[str, HoldingRow]) -> float:
    shared = set(a.keys()) & set(b.keys())
    if not shared:
        return 0.0

    a_weights = {t: a[t].weight for t in a if a[t].weight is not None}
    b_weights = {t: b[t].weight for t in b if b[t].weight is not None}
    if shared <= a_weights.keys() and shared <= b_weights.keys():
        overlap_weight = sum(min(a_weights[t], b_weights[t]) for t in shared)
        denominator = min(sum(a_weights.values()), sum(b_weights.values()))
        return round(100 * overlap_weight / denominator, 2) if denominator > 0 else 0.0

    # No usable weight data for at least one fund -- fall back to a plain
    # ticker-overlap ratio against the smaller holdings list.
    denominator = min(len(a), len(b))
    return round(100 * len(shared) / denominator, 2) if denominator > 0 else 0.0
