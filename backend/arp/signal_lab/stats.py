from __future__ import annotations

import math
from typing import Literal

import numpy as np
from pydantic import BaseModel

from arp.replication.characteristics_data import CharacteristicPanel
from arp.replication.price_data import PricePanel


def _average_ranks(a: np.ndarray) -> np.ndarray:
    order = np.argsort(a, kind="stable")
    sorted_a = a[order]
    ranks = np.empty(len(a))
    start = 0
    while start < len(a):
        end = start
        while end + 1 < len(a) and sorted_a[end + 1] == sorted_a[start]:
            end += 1
        ranks[order[start : end + 1]] = (start + end) / 2.0
        start = end + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3:
        return None
    rx = _average_ranks(np.asarray(x, dtype=float))
    ry = _average_ranks(np.asarray(y, dtype=float))
    dx, dy = rx - rx.mean(), ry - ry.mean()
    denom = float(np.sqrt((dx @ dx) * (dy @ dy)))
    # Constant side has zero rank variance: IC is undefined, not 0.
    if denom == 0.0:
        return None
    return float(dx @ dy) / denom


def rank_ic_series(
    scores: CharacteristicPanel,
    prices: PricePanel,
    *,
    forward_months: int = 1,
    min_names: int = 10,
) -> list[tuple[str, float]]:
    if forward_months < 1:
        raise ValueError(f"forward_months must be >= 1, got {forward_months}")
    # Index pairing is only valid on an identical grid; a shifted grid would silently misalign every IC.
    if scores.period_ends != prices.period_ends:
        raise ValueError(
            f"score and price grids differ ({len(scores.period_ends)} vs {len(prices.period_ends)} period_ends)"
        )

    def at(series: list[float | None], k: int) -> float | None:
        v = series[k] if k < len(series) else None
        return v if v is not None and math.isfinite(v) else None

    tickers = [t for t in scores.values if t in prices.returns]
    out: list[tuple[str, float]] = []
    for i, period_end in enumerate(scores.period_ends):
        j = i + forward_months
        if j >= len(prices.period_ends):
            break
        pairs = [
            (s, r)
            for t in tickers
            if (s := at(scores.values[t], i)) is not None and (r := at(prices.returns[t], j)) is not None
        ]
        if len(pairs) < min_names:
            continue
        ic = spearman([s for s, _ in pairs], [r for _, r in pairs])
        if ic is not None:
            out.append((period_end, ic))
    return out


def newey_west_t(values: list[float], lags: int | None = None) -> float | None:
    n = len(values)
    if n < 3:
        return None
    if lags is None:
        lags = int(4 * (n / 100) ** (2 / 9))
    x = np.asarray(values, dtype=float)
    mean = float(x.mean())
    e = x - mean
    long_run = float(e @ e) / n
    for lag in range(1, min(lags, n - 1) + 1):
        long_run += 2 * (1 - lag / (lags + 1)) * float(e[lag:] @ e[:-lag]) / n
    if long_run <= 0:
        return None
    return mean / float(np.sqrt(long_run / n))


class IcSummary(BaseModel):
    n: int
    mean: float | None
    t_nw: float | None
    hit_rate: float | None


def summarize_ic(series: list[tuple[str, float]]) -> IcSummary:
    ics = [ic for _, ic in series]
    if not ics:
        return IcSummary(n=0, mean=None, t_nw=None, hit_rate=None)
    return IcSummary(
        n=len(ics),
        mean=float(np.mean(ics)),
        t_nw=newey_west_t(ics),
        hit_rate=sum(ic > 0 for ic in ics) / len(ics),
    )


def mean_cross_correlation(a: CharacteristicPanel, b: CharacteristicPanel, *, min_names: int = 10) -> float | None:
    if a.period_ends != b.period_ends:
        raise ValueError(f"panel grids differ ({len(a.period_ends)} vs {len(b.period_ends)} period_ends)")

    def at(series: list[float | None], k: int) -> float | None:
        v = series[k] if k < len(series) else None
        return v if v is not None and math.isfinite(v) else None

    tickers = [t for t in a.values if t in b.values]
    corrs: list[float] = []
    for i in range(len(a.period_ends)):
        pairs = [
            (x, y)
            for t in tickers
            if (x := at(a.values[t], i)) is not None and (y := at(b.values[t], i)) is not None
        ]
        if len(pairs) < min_names:
            continue
        c = spearman([x for x, _ in pairs], [y for _, y in pairs])
        if c is not None:
            corrs.append(c)
    return float(np.mean(corrs)) if corrs else None


def compare_signals(
    a: list[float],
    b: list[float],
    *,
    n_comparisons: int,
    confidence: float = 0.95,
    n_boot: int = 2000,
    seed: int = 0,
    min_periods: int = 12,
) -> Literal["a_higher", "b_higher", "insufficient_data"]:
    if len(a) != len(b):
        raise ValueError(f"series lengths differ ({len(a)} vs {len(b)})")
    if len(a) < min_periods:
        return "insufficient_data"
    diff = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    if not np.isfinite(diff).all():
        return "insufficient_data"
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(diff), size=(n_boot, len(diff)))
    means = diff[idx].mean(axis=1)
    # Bonferroni: the more comparisons made, the wider the interval must clear zero.
    alpha = (1 - confidence) / max(1, n_comparisons)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    if lo > 0:
        return "a_higher"
    if hi < 0:
        return "b_higher"
    return "insufficient_data"
