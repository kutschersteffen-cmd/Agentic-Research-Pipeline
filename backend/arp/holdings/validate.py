"""Whole-file validation of holdings rows: all errors are collected, and any error rejects the file."""

import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from arp.schemas.issuer import lei_is_valid, normalise_lei

REQUIRED = {"index": ("isin", "weight"), "portfolio": ("isin", "weight", "market_value", "currency")}
TEMPLATE_COLUMNS = {
    "index": ("isin", "lei", "name", "weight", "shares", "free_float", "price", "currency"),
    "portfolio": ("isin", "lei", "name", "weight", "quantity", "price", "market_value", "currency", "fx_rate_to_eur"),
}
NUMERIC = ("weight", "shares", "free_float", "price", "quantity", "market_value", "fx_rate_to_eur")
WEIGHT_TOLERANCE = 0.5


def isin_is_valid(isin: str) -> bool:
    """ISO 6166: letters map to 10-35, Luhn over the resulting digit string."""
    if len(isin) != 12 or not isin.isascii() or not isin.isalnum() or not isin[:2].isalpha() or not isin[-1].isdigit():
        return False
    digits = "".join(str(int(c, 36)) for c in isin)
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 1:
            n *= 2
            n -= 9 if n > 9 else 0
        total += n
    return total % 10 == 0


def parse_decimal(value, decimal: str) -> float | None:
    if isinstance(value, bool):
        raise ValueError(value)
    if isinstance(value, (int, float)):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(value)
        return result
    other = "," if decimal == "." else "."
    text = str(value).replace(" ", "").replace(" ", "").replace("'", "").replace(other, "")
    if not text:
        return None
    result = float(text.replace(decimal, "."))
    if not math.isfinite(result):
        raise ValueError(value)
    return result


@dataclass(frozen=True)
class RowError:
    row: int | None
    column: str | None
    message: str


@dataclass
class Validated:
    rows: list[dict] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def validate(
    raw: list[dict],
    *,
    kind: str,
    as_of: str,
    decimal: str = ".",
    weight_unit: str = "percent",
    today: date | None = None,
) -> Validated:
    errors: list[RowError] = []
    for col in REQUIRED[kind]:
        if not any(col in r for r in raw):
            errors.append(RowError(None, col, "missing required column"))
    rows: list[dict] = []
    seen: set[str] = set()
    for r in raw:
        n = r.get("_row")
        row: dict = {}
        for col in REQUIRED[kind]:
            if col in r and _blank(r[col]):
                errors.append(RowError(n, col, "required"))
        isin = "" if _blank(r.get("isin")) else str(r["isin"]).strip().upper()
        if isin:
            if not isin_is_valid(isin):
                errors.append(RowError(n, "isin", "ISIN check digit fails"))
            elif isin in seen:
                errors.append(RowError(n, "isin", "duplicate position"))
            seen.add(isin)
        row["isin"] = isin
        lei = None if _blank(r.get("lei")) else normalise_lei(str(r["lei"]))
        if lei and not lei_is_valid(lei):
            errors.append(RowError(n, "lei", "LEI check digits fail (ISO 17442, mod 97)"))
        row["lei"] = lei
        name = r.get("name")
        if isinstance(name, float) and name.is_integer():
            name = int(name)
        row["name"] = None if _blank(name) else str(name).strip()
        if "currency" in r:
            row["currency"] = None if _blank(r["currency"]) else str(r["currency"]).strip().upper()
        for col in NUMERIC:
            v = r.get(col)
            try:
                row[col] = None if _blank(v) else parse_decimal(v, decimal)
            except (ValueError, OverflowError):
                row[col] = None
                errors.append(RowError(n, col, "not a number"))
        if row.get("weight") is not None and row["weight"] < 0:
            errors.append(RowError(n, "weight", "must not be negative"))
        fx = row.get("fx_rate_to_eur")
        if fx is not None and fx <= 0:
            errors.append(RowError(n, "fx_rate_to_eur", "must be positive"))
        elif fx is not None and row.get("currency") == "EUR" and fx != 1:
            errors.append(RowError(n, "fx_rate_to_eur", "must be 1 for a EUR position"))
        if row.get("weight") is not None and weight_unit == "fraction":
            row["weight"] *= 100
        if (
            kind == "portfolio"
            and row.get("currency")
            and row["currency"] != "EUR"
            and row.get("fx_rate_to_eur") is None
            and _blank(r.get("fx_rate_to_eur"))
        ):
            errors.append(RowError(n, "fx_rate_to_eur", "required for a non-EUR position; ARP never invents FX rates"))
        rows.append(row)
    s = sum(r["weight"] for r in rows if r.get("weight") is not None)
    if "weight" in REQUIRED[kind] and any(r.get("weight") is not None for r in rows) and abs(s - 100) > WEIGHT_TOLERANCE:
        errors.append(RowError(None, "weight", f"weights sum to {s:g}%, not 100% ± {WEIGHT_TOLERANCE:g}"))
    if date.fromisoformat(as_of) > (today or datetime.now(UTC).date()):
        errors.append(RowError(None, None, "as-of date is in the future"))
    return Validated([] if errors else rows, errors)
