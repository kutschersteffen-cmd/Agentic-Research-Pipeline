from __future__ import annotations

from arp.replication.price_data import PricePanel
from arp.schemas.strategy_replication import SignalType, StrategySpec


def momentum_scores(panel: PricePanel, formation_idx: int, formation_period_months: int, skip_month: bool) -> dict[str, float]:
    """Jegadeesh & Titman (1993)-style momentum score: compounded return
    over the J-month window ending at `formation_idx` (inclusive), skipping
    the most recent month first when `skip_month` (some later momentum
    papers do this to avoid 1-month reversal/microstructure effects; the
    original 1993 paper's headline strategies do not).

    A ticker missing any month in the window is excluded entirely -- never
    partially scored on fewer months than the paper's own definition.
    """
    j = formation_period_months
    end = formation_idx - (1 if skip_month else 0)
    start = end - j + 1
    if start < 0:
        return {}
    scores: dict[str, float] = {}
    for ticker, rets in panel.returns.items():
        window = rets[start : end + 1]
        if len(window) < j or any(r is None for r in window):
            continue
        cum = 1.0
        for r in window:
            cum *= 1.0 + r  # type: ignore[operator]
        scores[ticker] = cum - 1.0
    return scores


def compute_signal_scores(spec: StrategySpec, panel: PricePanel, formation_idx: int) -> dict[str, float]:
    """Dispatches to the scoring function for spec.signal_type. Add a new
    branch (and a new function above) for each new strategy family this
    module supports -- see SignalType."""
    if spec.signal_type == SignalType.MOMENTUM:
        return momentum_scores(panel, formation_idx, spec.formation_period_months, spec.skip_month)
    raise NotImplementedError(f"No signal implementation for {spec.signal_type!r}")


def assign_portfolios(scores: dict[str, float], num_portfolios: int) -> dict[str, int]:
    """Splits `scores` into `num_portfolios` contiguous buckets by rank,
    highest score first (bucket 1 = highest signal, bucket num_portfolios =
    lowest) -- the standard decile/quintile sort used by every strategy
    this module implements. Buckets are sized as evenly as possible; when
    the universe doesn't divide evenly, earlier (higher-signal) buckets
    absorb the remainder.
    """
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    n = len(ranked)
    buckets: dict[str, int] = {}
    for i, (ticker, _) in enumerate(ranked):
        bucket = min(num_portfolios, (i * num_portfolios) // n + 1)
        buckets[ticker] = bucket
    return buckets
