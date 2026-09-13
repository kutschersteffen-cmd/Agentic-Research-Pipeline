from __future__ import annotations

import logging
from dataclasses import replace

from arp.replication.backtest_engine import required_characteristic_names, run_backtest
from arp.replication.characteristics_data import CharacteristicDataSource, CharacteristicPanel
from arp.replication.compare import build_comparison_report
from arp.replication.price_data import PriceDataSource
from arp.schemas.common import JobStatus, RunManifest, new_id, now_iso
from arp.schemas.strategy_replication import ReplicationComparisonReport, SignalType, StrategySpec
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)


def _lookback_months(spec: StrategySpec) -> int:
    """The widest history/characteristic-lag window any part of `spec`
    needs before its own sample_period_start -- COMPOSITE takes the max
    across its components too, since each may need a different lookback
    (e.g. a 6-month momentum component alongside a 6-month-lagged value
    component)."""
    lookbacks = [spec.formation_period_months, spec.characteristic_lag_months]
    if spec.signal_type == SignalType.COMPOSITE:
        lookbacks += [c.formation_period_months for c in spec.composite_components]
        lookbacks += [c.characteristic_lag_months for c in spec.composite_components]
    return max(lookbacks)


def run_replication(
    spec: StrategySpec,
    tickers: list[str],
    price_source: PriceDataSource,
    *,
    run_store: RunStore,
    characteristics_sources: dict[str, CharacteristicDataSource] | None = None,
    benchmark_ticker: str | None = None,
    out_of_sample_start: str | None = None,
    out_of_sample_end: str | None = None,
) -> tuple[str, ReplicationComparisonReport]:
    """Runs one strategy replication end to end: fetches a price panel (and,
    for a characteristic-based signal_type such as VALUE/TEXT_SENTIMENT/
    COMPOSITE, one characteristics panel per entry in `characteristics_
    sources`, keyed by characteristic_name) wide enough to cover the
    spec's own lookback, backtests the in-sample window (spec.sample_
    period_start/end) against the paper's own rules, optionally backtests
    a separate out-of-sample window with the identical rules, compares
    both against the paper's reported performance, and persists everything
    under runs/<run_id>/ the same way every other run type in this
    codebase does. Returns (run_id, report).

    `tickers` is the concrete universe actually backtested -- distinct from
    spec.universe_description, which is only the paper's prose description
    of its own universe; reconstructing the paper's exact historical
    universe (e.g. "NYSE ordinary common shares" at each historical date)
    is out of scope for this pluggable-adapter version. See
    docs/STRATEGY_REPLICATION_METHODOLOGY.md.

    `characteristics_sources` must supply an entry for every characteristic_
    name spec's signal_type actually needs (see run_backtest's own
    validation) -- a COMPOSITE spec combining value + sentiment components
    needs two entries, keyed by each component's characteristic_name.
    """
    required = required_characteristic_names(spec)
    missing = required - set((characteristics_sources or {}).keys())
    if missing:
        raise ValueError(f"spec requires characteristics_sources for {sorted(missing)}, none were supplied for those names.")
    run_id = new_id("run")
    manifest = RunManifest(
        run_id=run_id,
        run_type="strategy_replication",
        status=JobStatus.RUNNING,
        params={
            "spec_id": spec.spec_id,
            "strategy_name": spec.strategy_name,
            "universe_size": len(tickers),
            "out_of_sample_start": out_of_sample_start,
            "out_of_sample_end": out_of_sample_end,
        },
    )
    run_store.save_manifest(manifest)
    run_store.append_jsonl(run_store.results_path(run_id), {"type": "spec", **spec.model_dump(mode="json")})

    try:
        # Fetch the union of the in-sample and out-of-sample windows (the
        # latter may fall before or after the former), so a single panel
        # and formation cache covers both backtest calls below.
        fetch_start = min(spec.sample_period_start, out_of_sample_start) if out_of_sample_start else spec.sample_period_start
        fetch_end = max(spec.sample_period_end, out_of_sample_end) if out_of_sample_end else spec.sample_period_end
        # Widen the fetch window backwards by the largest lookback any part
        # of the spec needs (MOMENTUM: formation_period_months; VALUE/
        # TEXT_SENTIMENT: characteristic_lag_months; COMPOSITE: the max
        # across its components too) so the earliest ranking month in
        # either window has real history/a real characteristic value
        # behind it, rather than silently starting the strategy late.
        lookback_years = (_lookback_months(spec) // 12) + 1
        fetch_start_padded = f"{int(fetch_start[:4]) - lookback_years}{fetch_start[4:]}"

        all_tickers = list(dict.fromkeys(tickers + ([benchmark_ticker] if benchmark_ticker else [])))
        panel = price_source.get_monthly_returns(all_tickers, fetch_start_padded, fetch_end)

        benchmark_returns = panel.returns.get(benchmark_ticker) if benchmark_ticker else None
        universe_panel = panel
        if benchmark_ticker:
            universe_panel = replace(panel, returns={t: r for t, r in panel.returns.items() if t != benchmark_ticker})

        characteristics: dict[str, CharacteristicPanel] = {}
        for name, source in (characteristics_sources or {}).items():
            char_panel = source.get_values(tickers, fetch_start_padded, fetch_end)
            if char_panel.period_ends != universe_panel.period_ends:
                raise ValueError(
                    f"characteristics_sources[{name!r}] returned a different set of period-ends than "
                    "price_source -- both must be prepared on the same monthly grid over the same fetch window. "
                    f"Got {len(char_panel.period_ends)} characteristic period(s) vs. "
                    f"{len(universe_panel.period_ends)} price period(s)."
                )
            characteristics[name] = char_panel

        # `universe_panel`/`characteristics` (and `benchmark_returns`,
        # aligned to the same period_ends) always cover the full fetched
        # range -- run_backtest itself restricts its *output* periods to
        # [period_start, period_end] while still using earlier months in
        # the panel for lookback, so both calls below share one fetch and
        # one formation cache instead of needing separately windowed panels.
        in_sample = run_backtest(
            spec,
            universe_panel,
            period_label="in_sample",
            period_start=spec.sample_period_start,
            period_end=spec.sample_period_end,
            benchmark_returns=benchmark_returns,
            characteristics=characteristics,
        )
        run_store.append_jsonl(run_store.results_path(run_id), {"type": "in_sample", **in_sample.model_dump(mode="json")})

        out_of_sample = None
        if out_of_sample_start and out_of_sample_end:
            out_of_sample = run_backtest(
                spec,
                universe_panel,
                period_label="out_of_sample",
                period_start=out_of_sample_start,
                period_end=out_of_sample_end,
                benchmark_returns=benchmark_returns,
                characteristics=characteristics,
            )
            run_store.append_jsonl(run_store.results_path(run_id), {"type": "out_of_sample", **out_of_sample.model_dump(mode="json")})

        report = build_comparison_report(in_sample, spec.reported_performance, out_of_sample=out_of_sample)
        run_store.append_jsonl(run_store.results_path(run_id), {"type": "comparison", **report.model_dump(mode="json")})

        manifest.status = JobStatus.COMPLETED
        manifest.completed_count = 1
        manifest.updated_at = now_iso()
        run_store.save_manifest(manifest)
        return run_id, report
    except Exception as exc:
        manifest.status = JobStatus.FAILED
        manifest.error = str(exc)
        run_store.save_manifest(manifest)
        raise
