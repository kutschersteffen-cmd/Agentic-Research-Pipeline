"""NACE helpers: code normalisation, official-table lookups and the EXIOBASE sector table."""

from __future__ import annotations

import csv
import re
from functools import cache
from pathlib import Path

from arp.research.value_chain.model import sector_name

_REF = Path(__file__).resolve().parent.parent
_SECTORS = _REF / "indirect_exposure" / "reference" / "exiobase_nace.csv"
_ISIC_NACE = _REF / "standards_mapping" / "reference" / "un_isic4_nace2.csv"
_NACE_ISIC = _REF / "standards_mapping" / "reference" / "un_nace2_isic4.csv"
_NACE_REVS = _REF / "standards_mapping" / "reference" / "eurostat_nace2_nace21.csv"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def normalise_nace(code: str) -> str:
    """`" 0729 "` -> `07.29`; anything past a class (`35.11.1`) is cut."""
    raw = code.strip()
    digits = re.sub(r"[\s.]", "", raw)
    if not digits.isdigit():
        return raw
    digits = digits[:4]
    return digits[:2] + ("." + digits[2:] if len(digits) > 2 else "")


@cache
def _headings(rev: str) -> dict[str, str]:
    if rev not in ("2", "2.1"):
        raise ValueError(f"unknown NACE revision {rev!r}")
    code, title = (
        ("NACE_Rev_2_Code", "NACE_Rev_2_Heading")
        if rev == "2"
        else ("NACE_Rev_21_Code", "NACE_Rev_21_Heading")
    )
    out: dict[str, str] = {}
    for r in _rows(_NACE_REVS):
        out.setdefault(r[code], r[title])
    return out


def nace_known(code: str, rev: str) -> bool:
    return code in _headings(rev)


def nace_title(code: str, rev: str) -> str | None:
    return _headings(rev).get(code)


def isic_to_nace2(isic4: str) -> list[str]:
    return sorted({r["NACE2code"] for r in _rows(_ISIC_NACE) if r["ISIC4code"] == isic4})


def nace2_to_isic4(code: str) -> list[str]:
    return sorted({r["ISIC4code"] for r in _rows(_NACE_ISIC) if r["NACE2code"] == code})


@cache
def _sector_rows() -> list[dict[str, str]]:
    return _rows(_SECTORS)


def nace_sectors(code: str, rev: str) -> set[str]:
    """EXIOBASE sectors with a table code matching `code`: equal, table coarser, or company coarser."""
    col = {"2": "nace2_code", "2.1": "nace21_code"}[rev]
    return {
        r["exiobase_sector"]
        for r in _sector_rows()
        if (t := r[col])
        and (t == code or code.startswith(t) and code[len(t)] in ".0123456789" or t.startswith(code))
    }


def code_set_sectors(scheme: str, code: str, rev: str) -> set[str]:
    """Sector names (suffix-free) of a value_chain.links.company_nace triple: a 4-digit ISIC Rev.4 class
    through the UN table, anything else (NACE code, 2-digit ISIC division) as a NACE code."""
    codes = isic_to_nace2(code) if scheme == "isic4" and len(code) == 4 else [code]
    return {sector_name(s) for c in codes for s in nace_sectors(c, rev)}


def division_sectors(division: str) -> set[str]:
    return nace_sectors(division, "2")


def sector_nace2_codes(sector: str) -> list[str]:
    return sorted({r["nace2_code"] for r in _sector_rows() if sector_name(r["exiobase_sector"]) == sector and r["nace2_code"]})
