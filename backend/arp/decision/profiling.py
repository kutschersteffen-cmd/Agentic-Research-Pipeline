from __future__ import annotations

import math
import statistics

from arp.decision.dataset import Dataset
from arp.decision.parsing import detect_decimal_comma, is_blank, to_bool, to_number
from arp.schemas.decision import ColumnProfile, ColumnStats

_MAX_LEVELS = 20


def quantile(sorted_values: list[float], q: float) -> float:
    """Linear interpolation between order statistics -- the definition the
    prototype used, kept identical so ported frameworks reproduce their
    original cut-points exactly."""
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_values[int(pos)]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def _sd(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def profile_column(dataset: Dataset, column: str) -> ColumnProfile:
    raw = dataset.column_values(column)
    n = len(raw)
    present = [v for v in raw if not is_blank(v)]
    unique = {str(v).strip().lower() for v in present}
    decimal_comma = detect_decimal_comma(present)
    numbers = [x for x in (to_number(v, decimal_comma) for v in present) if x is not None]
    booleans = [b for b in (to_bool(v) for v in present) if b is not None]

    coverage = len(present) / n if n else 0.0

    if present and len(booleans) / len(present) >= 0.95 and len(unique) <= 3:
        col_type = "boolean"
    elif present and len(numbers) / len(present) >= 0.8:
        all_int = all(float(x).is_integer() for x in numbers)
        col_type = "ordinal" if (all_int and len(unique) <= 7) else "numeric"
    elif len(unique) <= 12 and len(unique) < max(3, n * 0.5):
        col_type = "categorical"
    elif n and len(unique) >= n * 0.9:
        col_type = "identifier"
    else:
        col_type = "text"

    stats: ColumnStats | None = None
    levels: list[str] = []
    if col_type in ("numeric", "ordinal"):
        s = sorted(numbers)
        stats = ColumnStats(
            count=len(s),
            min=s[0] if s else None,
            p5=quantile(s, 0.05) if s else None,
            q1=quantile(s, 0.25) if s else None,
            median=quantile(s, 0.5) if s else None,
            q3=quantile(s, 0.75) if s else None,
            p95=quantile(s, 0.95) if s else None,
            max=s[-1] if s else None,
            mean=statistics.fmean(s) if s else None,
            sd=_sd(s),
        )
        spread = bool(s) and s[0] != s[-1]
    elif col_type == "boolean":
        stats = ColumnStats(count=len(booleans), true_share=(sum(booleans) / len(booleans)) if booleans else None)
        spread = len(set(booleans)) > 1
    else:
        levels = list(dict.fromkeys(str(v).strip() for v in present))[:_MAX_LEVELS]
        spread = len(unique) > 1

    return ColumnProfile(
        name=column,
        type=col_type,
        coverage=coverage,
        unique=len(unique),
        spread=spread,
        decimal_comma=decimal_comma,
        stats=stats,
        levels=levels,
    )


def profile_dataset(dataset: Dataset) -> dict[str, ColumnProfile]:
    return {c: profile_column(dataset, c) for c in dataset.columns}


def numeric_values(dataset: Dataset, profile: ColumnProfile) -> list[float | None]:
    """A column's per-row value on the 'scoreable' scale: numbers as
    numbers, booleans as 1/0, anything else as None."""
    raw = dataset.column_values(profile.name)
    if profile.type == "boolean":
        return [None if b is None else float(b) for b in (to_bool(v) for v in raw)]
    if profile.type in ("numeric", "ordinal"):
        return [to_number(v, profile.decimal_comma) for v in raw]
    return [None] * len(raw)
