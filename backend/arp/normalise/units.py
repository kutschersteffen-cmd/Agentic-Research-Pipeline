"""Unit and scale normalisation over the versioned CSV tables in ``tables/``."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

UNITS_TABLE = "units_v1"
SCALE_TABLE = "scale_v1"
_TABLES = Path(__file__).parent / "tables"


@dataclass(frozen=True)
class UnitInfo:
    canonical: str
    factor: float
    dimension: str
    ambiguous: bool


@dataclass(frozen=True)
class Conversion:
    value: float | None
    scale_applied: float
    from_canonical: str | None
    ambiguous: bool
    reason: str | None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _read(name: str) -> list[dict[str, str]]:
    with open(_TABLES / f"{name}.csv", encoding="utf8", newline="") as f:
        return list(csv.DictReader(f))


@cache
def _units() -> dict[str, UnitInfo]:
    return {
        _norm(r["alias"]): UnitInfo(r["canonical"], float(r["factor"]), r["dimension"], r["ambiguous"] == "1")
        for r in _read(UNITS_TABLE)
    }


@cache
def _scales() -> dict[str, tuple[float, bool]]:
    return {_norm(r["word"]): (float(r["factor"]), r["ambiguous"] == "1") for r in _read(SCALE_TABLE)}


def lookup_unit(text: str) -> UnitInfo | None:
    return _units().get(_norm(text))


def split_unit(text: str) -> tuple[float, bool, str]:
    """Split a leading or trailing scale word off ``text``: (scale, scale_ambiguous, base_text)."""
    text = re.sub(r"\s+", " ", text).strip()
    if lookup_unit(text) is None:
        words = text.split(" ")
        if len(words) > 1:
            for scale_word, base in ((words[0], words[1:]), (words[-1], words[:-1])):
                hit = _scales().get(_norm(scale_word))
                if hit:
                    return hit[0], hit[1], " ".join(base)
    return 1.0, False, text


def convert(value: float, from_text: str, to_text: str) -> Conversion:
    from_scale, from_amb, from_base = split_unit(from_text)
    to_scale, to_amb, to_base = split_unit(to_text)
    src, dst = lookup_unit(from_base), lookup_unit(to_base)
    if src is None or dst is None:
        return Conversion(None, from_scale, None, False, "unknown_unit")
    ambiguous = from_amb or to_amb or src.ambiguous or dst.ambiguous

    def fail(reason: str) -> Conversion:
        return Conversion(None, from_scale, src.canonical, ambiguous, reason)

    if src.dimension != dst.dimension:
        return fail("dimension_mismatch")
    if src.dimension == "currency" and src.canonical != dst.canonical:
        return fail("needs_fx")
    out = value * from_scale * src.factor / (to_scale * dst.factor)
    return Conversion(out, from_scale, src.canonical, ambiguous, None)
