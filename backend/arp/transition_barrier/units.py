"""Unit conversion for extracted facts, from the rule book's `conversions` table."""

from __future__ import annotations


def convert(value: float, unit: str, fact_unit: str, year: int, conversions: list[dict]) -> tuple[float | None, str | None]:
    """`(converted, None)`, or `(None, reason)`. Each side of the first `/` converts on its own, with the newest
    rate whose year is at most `year`; a denominator rate divides (a per-gallon price ÷ 3.785… is per litre)."""
    if unit == fact_unit:
        return value, None
    src, src_slash, src_per = unit.partition("/")
    dst, dst_slash, dst_per = fact_unit.partition("/")
    pairs = [(a, b, inverse) for a, b, inverse in ((src, dst, False), (src_per, dst_per, True)) if a != b]
    rows = {(a, b): [r for r in conversions if r["from"] == a and r["to"] == b] for a, b, _ in pairs}
    if src_slash != dst_slash or not all(rows.values()):
        return None, f"Unit not convertible: {unit or '(no unit)'}"
    factor = 1.0
    for a, b, inverse in pairs:
        usable = [r for r in rows[a, b] if r["year"] <= year]
        if not usable:
            return None, f"No {a} to {b} rate for {year} or earlier"
        rate = max(usable, key=lambda r: r["year"])["rate"]
        factor = factor / rate if inverse else factor * rate
    return value * factor, None
