"""Annual-average FX rates, crossed through USD.

``tables/fx_v1.csv`` holds ``usd_per_unit`` (USD per one unit of the currency) from the
Federal Reserve G.5A annual release. G.5A quotes EUR, GBP and AUD as USD per unit
and every other currency as units per USD; the latter were inverted (1/x, rounded to
8 decimals) when the table was built.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import cache
from pathlib import Path

FX_TABLE = "fx_v1"
FX_POLICY = "annual_average_of_period_end_year"


@dataclass(frozen=True)
class FxRate:
    rate: float
    ref: str


@cache
def _usd_per_unit() -> dict[tuple[str, int], float]:
    path = Path(__file__).parent / "tables" / f"{FX_TABLE}.csv"
    with open(path, encoding="utf8", newline="") as f:
        return {(r["currency"], int(r["year"])): float(r["usd_per_unit"]) for r in csv.DictReader(f)}


def rate(from_ccy: str, to_ccy: str, year: int) -> FxRate | None:
    table = _usd_per_unit()
    src = 1.0 if from_ccy == "USD" else table.get((from_ccy, year))
    dst = 1.0 if to_ccy == "USD" else table.get((to_ccy, year))
    if src is None or dst is None:
        return None
    return FxRate(src / dst, f"{FX_TABLE}:{from_ccy}->{to_ccy}:{year}")


def convert_amount(value: float, from_ccy: str, to_ccy: str, year: int) -> tuple[float | None, FxRate | None]:
    fx = rate(from_ccy, to_ccy, year)
    return (None, None) if fx is None else (value * fx.rate, fx)
