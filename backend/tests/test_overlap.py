from arp.research.taxonomy_sources.overlap import compute_holdings_overlap
from arp.schemas.taxonomy_sources import HoldingRow


def _row(ticker, weight=None, name=None):
    return HoldingRow(ticker=ticker, name=name or ticker, weight=weight)


def test_core_and_union_tickers():
    result = compute_holdings_overlap(
        {
            "Fund A": [_row("AAA"), _row("BBB"), _row("CCC")],
            "Fund B": [_row("AAA"), _row("BBB"), _row("DDD")],
        }
    )
    assert result.core_tickers == ["AAA", "BBB"]
    assert result.union_tickers == ["AAA", "BBB", "CCC", "DDD"]
    assert result.ticker_presence["AAA"] == ["Fund A", "Fund B"]
    assert result.ticker_presence["CCC"] == ["Fund A"]


def test_three_fund_core_requires_presence_in_all():
    result = compute_holdings_overlap(
        {
            "A": [_row("X"), _row("Y")],
            "B": [_row("X"), _row("Y")],
            "C": [_row("X")],
        }
    )
    assert result.core_tickers == ["X"]  # Y is missing from C
    assert set(result.union_tickers) == {"X", "Y"}


def test_weighted_pairwise_overlap_hand_computed():
    # Fund A: AAA=0.10, BBB=0.05 (total 0.15); Fund B: AAA=0.08, BBB=0.02 (total 0.10)
    # shared overlap weight = min(.10,.08) + min(.05,.02) = 0.08 + 0.02 = 0.10
    # denominator = min(0.15, 0.10) = 0.10 -> 100%
    result = compute_holdings_overlap(
        {
            "A": [_row("AAA", weight=0.10), _row("BBB", weight=0.05)],
            "B": [_row("AAA", weight=0.08), _row("BBB", weight=0.02)],
        }
    )
    assert result.pairwise_overlap_pct["A|B"] == 100.0


def test_no_shared_tickers_zero_overlap():
    result = compute_holdings_overlap({"A": [_row("AAA")], "B": [_row("BBB")]})
    assert result.pairwise_overlap_pct["A|B"] == 0.0
    assert result.core_tickers == []


def test_missing_weights_falls_back_to_ticker_count_ratio():
    # no weight data at all -> fall back to shared/min(len) ratio
    result = compute_holdings_overlap(
        {
            "A": [_row("AAA"), _row("BBB"), _row("CCC")],
            "B": [_row("AAA"), _row("BBB")],
        }
    )
    # shared = {AAA, BBB} = 2, min(len)=2 -> 100%
    assert result.pairwise_overlap_pct["A|B"] == 100.0
