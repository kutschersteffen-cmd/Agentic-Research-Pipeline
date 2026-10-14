from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from arp.replication.backtest_engine import run_backtest
from arp.replication.characteristics_data import CharacteristicPanel
from arp.replication.deflated_sharpe import deflated_sharpe_ratio
from arp.replication.price_data import PricePanel
from arp.schemas.strategy_replication import (
    DeflatedSharpeAssessment,
    LegPerformance,
    SignalType,
    StrategySpec,
)
from arp.signal_lab.cutoffs import CutoffTable, period_window
from arp.signal_lab.stats import IcSummary, mean_cross_correlation, rank_ic_series, summarize_ic

Window = Literal["in_window", "post_cutoff"]


class WindowEvidence(BaseModel):
    window: Window
    # Score months of this window inside the sample, not IC pairs; the graduation gate reads ic.n instead.
    periods: int
    ic: IcSummary
    long_short: LegPerformance | None
    net_long_short: LegPerformance | None
    monthly_turnover_pct: float | None
    deflated_sharpe: DeflatedSharpeAssessment | None


class EvidenceReport(BaseModel):
    windows: list[WindowEvidence]
    contamination_gap_ic: float | None
    overlap: dict[str, float | None]
    n_trials: int


def sentiment_spec(characteristic_name: str, *, start: str, end: str, num_portfolios: int = 5) -> StrategySpec:
    return StrategySpec(
        paper_citation="lab experiment",
        paper_title="lab experiment",
        strategy_name=f"lab: {characteristic_name}",
        signal_type=SignalType.TEXT_SENTIMENT,
        universe_description="lab experiment",
        holding_period_months=1,
        characteristic_name=characteristic_name,
        characteristic_lag_months=0,
        num_portfolios=num_portfolios,
        long_leg_portfolio=1,
        short_leg_portfolio=num_portfolios,
        sample_period_start=start,
        sample_period_end=end,
    )


def evaluate_signal(
    scores: CharacteristicPanel,
    prices: PricePanel,
    spec: StrategySpec,
    *,
    model: str | None,
    cutoffs: CutoffTable,
    cost_bps: float = 10.0,
    n_trials: int = 1,
    baselines: dict[str, CharacteristicPanel] | None = None,
    forward_months: int = 1,
) -> EvidenceReport:
    ends = scores.period_ends
    # Window follows the FORMATION month: a portfolio built from possibly memorised scores
    # must not have its return counted as post-cutoff.
    by_window: dict[Window, list[int]] = {"in_window": [], "post_cutoff": []}
    for i, end in enumerate(ends):
        if spec.sample_period_start <= end <= spec.sample_period_end:
            by_window[period_window(model, end, cutoffs)].append(i)

    ic_all = rank_ic_series(scores, prices, forward_months=forward_months)
    characteristics = {spec.characteristic_name: scores}  # type: ignore[dict-item]

    windows: list[WindowEvidence] = []
    for window, idxs in by_window.items():
        if not idxs:
            continue
        members = {ends[i] for i in idxs}
        ic = summarize_ic([(d, v) for d, v in ic_all if d in members])
        allowed = {ends[i + forward_months] for i in idxs if i + forward_months < len(ends)}
        bt = run_backtest(
            spec,
            prices,
            period_label=window,
            period_start=spec.sample_period_start,
            period_end=spec.sample_period_end,
            characteristics=characteristics,
            allowed_period_ends=allowed,
            cost_bps=cost_bps,
        )
        net = bt.net_long_short is not None
        series = [
            p.long_short_return_pct - (cost_bps / 10000 * p.traded_weight * 100 if net else 0.0)
            for p in bt.periods
        ]
        windows.append(
            WindowEvidence(
                window=window,
                periods=len(idxs),
                ic=ic,
                long_short=bt.long_short,
                net_long_short=bt.net_long_short,
                monthly_turnover_pct=bt.monthly_turnover_pct,
                deflated_sharpe=deflated_sharpe_ratio(series, n_trials=n_trials) if series else None,
            )
        )

    ic_mean = {w.window: w.ic.mean for w in windows}
    gap = None
    if ic_mean.get("in_window") is not None and ic_mean.get("post_cutoff") is not None:
        gap = ic_mean["in_window"] - ic_mean["post_cutoff"]
    overlap = {name: mean_cross_correlation(scores, b) for name, b in (baselines or {}).items()}
    return EvidenceReport(windows=windows, contamination_gap_ic=gap, overlap=overlap, n_trials=n_trials)
