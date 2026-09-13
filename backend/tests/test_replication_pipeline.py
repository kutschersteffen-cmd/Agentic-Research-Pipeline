import csv

from arp.replication.pipeline import run_replication
from arp.replication.price_data import CsvPriceSource
from arp.schemas.common import JobStatus
from arp.schemas.strategy_replication import RebalanceFrequency, SignalType, StrategySpec, WeightingScheme
from arp.storage.run_store import RunStore

_BENCH_CYCLE = [1.01, 0.995, 1.02, 0.99, 1.005, 1.0]  # varying, not constant -- a degenerate zero-variance
# benchmark makes beta/alpha genuinely unidentifiable (no regressor variance to fit against), which is a
# real property of compute_leg_performance, not something this fixture should trigger by accident.


def _write_prices_csv(path, n_months=48):
    tickers = ["WIN1", "WIN2", "LOSE1", "LOSE2", "BENCH"]
    prices = {t: 100.0 for t in tickers}
    rows = []
    year, month = 1998, 1
    for i in range(n_months):
        rows.append((f"{year}-{month:02d}-01", dict(prices)))
        prices["WIN1"] *= 1.02
        prices["WIN2"] *= 1.025
        prices["LOSE1"] *= 0.99
        prices["LOSE2"] *= 0.985
        prices["BENCH"] *= _BENCH_CYCLE[i % len(_BENCH_CYCLE)]
        month += 1
        if month > 12:
            month = 1
            year += 1
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", *tickers])
        for date, snap in rows:
            writer.writerow([date, *(snap[t] for t in tickers)])


def _spec() -> StrategySpec:
    return StrategySpec(
        paper_citation="Test (2020)",
        paper_title="Test paper",
        strategy_name="test momentum",
        signal_type=SignalType.MOMENTUM,
        universe_description="synthetic",
        formation_period_months=3,
        holding_period_months=3,
        rebalance_frequency=RebalanceFrequency.MONTHLY,
        num_portfolios=2,
        long_leg_portfolio=1,
        short_leg_portfolio=2,
        weighting=WeightingScheme.EQUAL,
        sample_period_start="1999-01-01",
        sample_period_end="2000-12-01",
    )


def test_run_replication_persists_manifest_and_results(tmp_path):
    prices_csv = tmp_path / "prices.csv"
    _write_prices_csv(prices_csv)
    source = CsvPriceSource(prices_csv)
    run_store = RunStore(tmp_path / "runs")

    run_id, report = run_replication(
        _spec(),
        ["WIN1", "WIN2", "LOSE1", "LOSE2"],
        source,
        run_store=run_store,
        benchmark_ticker="BENCH",
        out_of_sample_start="2001-01-01",
        out_of_sample_end="2001-12-01",
    )

    manifest = run_store.load_manifest(run_id)
    assert manifest is not None
    assert manifest.run_type == "strategy_replication"
    assert manifest.status == JobStatus.COMPLETED

    rows = run_store.read_jsonl(run_store.results_path(run_id))
    row_types = [r["type"] for r in rows]
    assert row_types == ["spec", "in_sample", "out_of_sample", "comparison"]

    in_sample_row = rows[1]
    out_of_sample_row = rows[2]
    assert in_sample_row["period_start"] == "1999-01-01"
    assert in_sample_row["period_end"] == "2000-12-01"
    assert out_of_sample_row["period_start"] == "2001-01-01"
    assert out_of_sample_row["period_end"] == "2001-12-01"
    # Winners persistently beat losers -- both windows should show a
    # positive long-short spread, with a benchmark-relative alpha/beta
    # computed since a benchmark ticker was supplied.
    assert in_sample_row["long_short"]["annualized_return_pct"] > 0
    assert in_sample_row["long_short"]["beta"] is not None

    assert report.spec_id == rows[0]["spec_id"]
    assert report.verdict is not None


def test_run_replication_without_out_of_sample_window(tmp_path):
    prices_csv = tmp_path / "prices.csv"
    _write_prices_csv(prices_csv)
    source = CsvPriceSource(prices_csv)
    run_store = RunStore(tmp_path / "runs")

    run_id, report = run_replication(_spec(), ["WIN1", "WIN2", "LOSE1", "LOSE2"], source, run_store=run_store)
    rows = run_store.read_jsonl(run_store.results_path(run_id))
    assert [r["type"] for r in rows] == ["spec", "in_sample", "comparison"]
    assert report.out_of_sample is None


def test_run_replication_marks_manifest_failed_on_error(tmp_path):
    prices_csv = tmp_path / "prices.csv"
    _write_prices_csv(prices_csv)
    source = CsvPriceSource(prices_csv)
    run_store = RunStore(tmp_path / "runs")

    try:
        # "NOPE" has no column in the CSV -> CsvPriceSource.get_monthly_returns raises ValueError.
        run_replication(_spec(), ["NOPE"], source, run_store=run_store)
        raised = False
    except ValueError:
        raised = True
    assert raised

    run_id = run_store.list_runs("strategy_replication")[0].run_id
    manifest = run_store.load_manifest(run_id)
    assert manifest.status == JobStatus.FAILED
    assert manifest.error
