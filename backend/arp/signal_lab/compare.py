from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from arp.schemas.strategy_replication import LegPerformance
from arp.signal_lab.registry import ExperimentRecord, Registry
from arp.signal_lab.stats import compare_signals

_SHARED_FIELDS = ("universe", "window_start", "window_end", "cost_bps")


class Comparison(BaseModel):
    a: str
    b: str
    verdict: Literal["a_higher", "b_higher", "insufficient_data"]
    months: int
    n_comparisons: int
    reason: str | None = None


def _post_cutoff(record: ExperimentRecord):
    return next((w for w in record.evidence.windows if w.window == "post_cutoff"), None)


def compare_experiments(a_id: str, b_id: str, registry: Registry, *, confidence: float = 0.95) -> Comparison:
    experiments = registry.list_experiments()
    by_id = {r.experiment_id: r for r in experiments}
    for experiment_id in (a_id, b_id):
        if experiment_id not in by_id:
            raise ValueError(f"unknown experiment {experiment_id!r}")
    if a_id == b_id:
        raise ValueError("cannot compare an experiment with itself")
    a, b = by_id[a_id], by_id[b_id]
    for field in _SHARED_FIELDS:
        if getattr(a.recipe, field) != getattr(b.recipe, field):
            raise ValueError(
                f"not comparable: {field} differs ({getattr(a.recipe, field)!r} vs {getattr(b.recipe, field)!r})"
            )
    # Every pair that could be compared counts, so asking more questions makes each answer harder to win.
    k = sum(all(getattr(r.recipe, f) == getattr(a.recipe, f) for f in _SHARED_FIELDS) for r in experiments)
    n_comparisons = max(1, k * (k - 1) // 2)

    windows = {r.experiment_id: _post_cutoff(r) for r in (a, b)}
    for experiment_id, window in windows.items():
        if window is None:
            return Comparison(
                a=a_id, b=b_id, verdict="insufficient_data", months=0, n_comparisons=n_comparisons,
                reason=f"no post-cutoff evidence for {experiment_id}",
            )
    for experiment_id, window in windows.items():
        if not window.series and window.periods > 0 and window.long_short in (None, LegPerformance()):
            # The backtest produced no months (a real answer); an old row has a long_short but no stored series.
            return Comparison(
                a=a_id, b=b_id, verdict="insufficient_data", months=0, n_comparisons=n_comparisons,
                reason=f"no post-cutoff portfolio months for {experiment_id}",
            )
        if not window.series:
            raise ValueError(f"{experiment_id} was registered before series were stored; re-run it")

    a_series, b_series = dict(windows[a_id].series), dict(windows[b_id].series)
    common = sorted(a_series.keys() & b_series.keys())
    verdict = compare_signals(
        [a_series[p] for p in common], [b_series[p] for p in common],
        n_comparisons=n_comparisons, confidence=confidence,
    )
    return Comparison(a=a_id, b=b_id, verdict=verdict, months=len(common), n_comparisons=n_comparisons)
