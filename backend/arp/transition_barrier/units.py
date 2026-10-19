"""Currency conversion for extracted facts, from the rule book's `conversions` table."""

from __future__ import annotations


def convert(value: float, unit: str, fact_unit: str, year: int, conversions: list[dict]) -> tuple[float | None, str | None]:
    """`(converted, None)`, or `(None, reason)`. Uses the newest rate whose year is at most `year`."""
    if unit == fact_unit:
        return value, None
    src, _, src_per = unit.partition("/")
    dst, _, dst_per = fact_unit.partition("/")
    rows = [r for r in conversions if r["from"] == src and r["to"] == dst] if src_per == dst_per else []
    if not rows:
        return None, f"Unit not convertible: {unit}"
    usable = [r for r in rows if r["year"] <= year]
    if not usable:
        return None, f"No {src} to {dst} rate for {year} or earlier"
    return value * max(usable, key=lambda r: r["year"])["rate"], None
