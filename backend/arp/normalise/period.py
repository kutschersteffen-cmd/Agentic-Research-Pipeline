"""Period, basis and qualifier normalisation (stdlib only)."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from functools import cache
from pathlib import Path

BASIS_TABLE = "basis_v1"
_TABLES = Path(__file__).parent / "tables"
_DATE_FORMATS = ("%d %B %Y", "%B %d, %Y", "%d %b %Y", "%b %d, %Y", "%Y-%m-%d")
_DATE = r"(\d{4}-\d{2}-\d{2}|\d{1,2} [A-Za-z]+ \d{4}|[A-Za-z]+ \d{1,2}, \d{4})"
_WEEKS = re.compile(rf"\b(52|53) weeks ended {_DATE}", re.I)
_YEAR_ENDED = re.compile(rf"\b(?:fiscal )?year ended {_DATE}", re.I)
_AS_AT = re.compile(rf"\bas (?:at|of) {_DATE}", re.I)
_FY = re.compile(r"(?:FY ?|Fiscal (?:year )?)?(\d{4})(?:[/-](\d{4}|\d{2}))?", re.I)
_FY_SHORT = re.compile(r"(?:FY ?|Fiscal (?:year )?)(\d{2})", re.I)  # "FY24": 21st century
_QUARTER = re.compile(r"Q([1-4]) (\d{4})", re.I)


@dataclass(frozen=True)
class ResolvedPeriod:
    start: date | None
    end: date | None
    fye_assumed: bool = False


def _parse_date(text: str) -> date | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _year_start(end: date) -> date:
    # The day after the same month-day one year earlier (Feb 29 clamps to Feb 28 first).
    try:
        prev = end.replace(year=end.year - 1)
    except ValueError:
        prev = date(end.year - 1, 2, 28)
    return prev + timedelta(days=1)


def _fiscal_end(year: int, mmdd: str) -> date:
    month, day = int(mmdd[:2]), int(mmdd[3:])
    try:
        return date(year, month, day)
    except ValueError:
        if (month, day) == (2, 29):  # leap-day year end in a common year
            return date(year, 2, 28)
        raise


def resolve_period(text: str | None, *, fiscal_year_end: str | None) -> ResolvedPeriod:
    """Resolve period text; a fiscal year is labelled by the calendar year it ends in."""
    none = ResolvedPeriod(None, None)
    text = (text or "").strip()
    if not text:
        return none
    if m := _WEEKS.search(text):
        end = _parse_date(m[2])
        return ResolvedPeriod(end - timedelta(days=int(m[1]) * 7 - 1), end) if end else none
    if m := _YEAR_ENDED.search(text):
        end = _parse_date(m[1])
        return ResolvedPeriod(_year_start(end), end) if end else none
    if m := _AS_AT.search(text):
        end = _parse_date(m[1])
        return ResolvedPeriod(end, end) if end else none
    if m := _QUARTER.fullmatch(text):
        q, y = int(m[1]), int(m[2])
        start = date(y, 3 * q - 2, 1)
        end = (date(y + (q == 4), 1 if q == 4 else 3 * q + 1, 1)) - timedelta(days=1)
        return ResolvedPeriod(start, end)
    if m := _FY_SHORT.fullmatch(text):
        return _fiscal_year(2000 + int(m[1]), fiscal_year_end)
    if m := _FY.fullmatch(text):
        year = int(m[1])
        if m[2]:  # a split year ("2023/24", "2023-2024") ends in the second, consecutive year
            if int(m[2]) != (year + 1 if len(m[2]) == 4 else (year + 1) % 100):
                return none
            year += 1
        return _fiscal_year(year, fiscal_year_end)
    end = _parse_date(text)  # a bare date is a point in time, like "as at"
    return ResolvedPeriod(end, end) if end else none


def _fiscal_year(year: int, fiscal_year_end: str | None) -> ResolvedPeriod:
    assumed = False
    try:
        if fiscal_year_end is None:
            raise ValueError
        end = _fiscal_end(year, fiscal_year_end)
    except ValueError:
        end, assumed = date(year, 12, 31), True
    return ResolvedPeriod(_year_start(end), end, assumed)


@cache
def _basis() -> dict[str, str]:
    with open(_TABLES / f"{BASIS_TABLE}.csv", encoding="utf8", newline="") as f:
        return {re.sub(r"\s+", " ", r["alias"]).strip().casefold(): r["canonical"] for r in csv.DictReader(f)}


def normalise_basis(text: str | None) -> str | None:
    if not text:
        return None
    return _basis().get(re.sub(r"\s+", " ", text).strip().casefold())


class Qualifier(StrEnum):
    ESTIMATED = "estimated"
    RESTATED = "restated"
    PARTIAL_COVERAGE = "partial_coverage"
    FISCAL_YEAR_END_ASSUMED = "fiscal_year_end_assumed"


_KEYWORDS = {
    Qualifier.ESTIMATED: re.compile(r"estimate|approx|~|(?<!\w)c\.", re.I),
    Qualifier.RESTATED: re.compile(r"restated|re-stated|revised", re.I),
    Qualifier.PARTIAL_COVERAGE: re.compile(r"partial|excluding|excl\.|covers|% of sites|% of operations", re.I),
}


def detect_qualifiers(*texts: str | None) -> list[Qualifier]:
    blob = " ".join(t for t in texts if t)
    return [q for q, rx in _KEYWORDS.items() if rx.search(blob)]


def reported_precision(raw: str | None) -> int | None:
    m = re.search(r"\d[\d,]*(?:\.(\d+))?", raw or "")
    return None if not m else len(m[1] or "")
