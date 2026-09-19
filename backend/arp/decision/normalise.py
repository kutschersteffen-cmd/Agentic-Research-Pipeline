from __future__ import annotations

import statistics
from collections import defaultdict

from arp.decision.profiling import quantile
from arp.schemas.decision import ColumnProfile, Direction, NormMethod

NEUTRAL = 50.0


def _percentile_ranks(values: list[float | None], indices: list[int]) -> dict[int, float]:
    """Average-rank percentiles, ties sharing a rank. A single present
    value maps to the neutral midpoint rather than to 0 or 100 -- with
    nothing to compare against, neither extreme is defensible."""
    present = [(values[i], i) for i in indices if values[i] is not None]
    if not present:
        return {}
    if len(present) == 1:
        return {present[0][1]: NEUTRAL}
    ordered = sorted(present, key=lambda pair: pair[0])
    out: dict[int, float] = {}
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][0] == ordered[i][0]:
            j += 1
        avg = (i + j) / 2
        for k in range(i, j + 1):
            out[ordered[k][1]] = avg / (len(ordered) - 1) * 100.0
        i = j + 1
    return out


def _linear(values: list[float | None], indices: list[int], method: NormMethod, winsor_pct: float) -> dict[int, float]:
    present = sorted(values[i] for i in indices if values[i] is not None)
    if not present:
        return {}
    w = max(0.0, min(0.2, winsor_pct / 100.0))
    lo, hi = quantile(present, w), quantile(present, 1 - w)
    out: dict[int, float] = {}
    if method == "minmax":
        for i in indices:
            v = values[i]
            if v is None:
                continue
            out[i] = NEUTRAL if hi == lo else max(0.0, min(100.0, (min(max(v, lo), hi) - lo) / (hi - lo) * 100.0))
        return out
    winsorised = [min(max(v, lo), hi) for v in present]
    mean = statistics.fmean(winsorised)
    sd = statistics.stdev(winsorised) if len(winsorised) > 1 else 0.0
    sd = sd or 1.0
    for i in indices:
        v = values[i]
        if v is None:
            continue
        out[i] = max(0.0, min(100.0, NEUTRAL + 15.0 * ((min(max(v, lo), hi) - mean) / sd)))
    return out


def _normalise_block(values: list[float | None], indices: list[int], method: NormMethod, winsor_pct: float) -> dict[int, float]:
    if method == "percentile":
        return _percentile_ranks(values, indices)
    return _linear(values, indices, method, winsor_pct)


def normalise_column(
    values: list[float | None],
    profile: ColumnProfile,
    *,
    method: NormMethod,
    winsor_pct: float,
    direction: Direction,
    cohorts: list[str | None] | None = None,
    min_cohort_size: int = 5,
) -> list[float | None]:
    """A column's values on a common 0-100 scale, high always meaning good.

    Booleans map straight to 0/100 and bypass winsorising entirely --
    there are no tails on a two-valued column to trim.

    When `cohorts` is supplied, each criterion is normalised inside its
    peer group instead of across the whole table. Cohorts with fewer than
    `min_cohort_size` present values fall back to the whole-table
    normalisation: ranking three peers against each other produces a
    confident-looking number backed by nothing.
    """
    n = len(values)
    if profile.type == "boolean":
        scaled: list[float | None] = [None if v is None else (100.0 if v >= 0.5 else 0.0) for v in values]
    else:
        whole = _normalise_block(values, list(range(n)), method, winsor_pct)
        resolved = dict(whole)
        if cohorts:
            groups: dict[str, list[int]] = defaultdict(list)
            for i, cohort in enumerate(cohorts):
                if cohort:
                    groups[cohort].append(i)
            for indices in groups.values():
                if sum(1 for i in indices if values[i] is not None) < min_cohort_size:
                    continue
                resolved.update(_normalise_block(values, indices, method, winsor_pct))
        scaled = [resolved.get(i) for i in range(n)]

    if direction == "lower":
        return [None if v is None else 100.0 - v for v in scaled]
    return scaled


def spearman(a: list[float | None], b: list[float | None]) -> float:
    """Rank correlation over the rows where both columns are present.
    Fewer than five shared rows returns 0 -- too little to group on."""
    pairs = [(x, y) for x, y in zip(a, b, strict=True) if x is not None and y is not None]
    if len(pairs) < 5:
        return 0.0

    def ranks(index: int) -> list[float]:
        ordered = sorted(range(len(pairs)), key=lambda i: pairs[i][index])
        out = [0.0] * len(pairs)
        for position, i in enumerate(ordered):
            out[i] = float(position)
        return out

    ra, rb = ranks(0), ranks(1)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    da = sum((x - ma) ** 2 for x in ra)
    db = sum((y - mb) ** 2 for y in rb)
    return num / (da * db) ** 0.5 if da and db else 0.0
