from __future__ import annotations

import csv
import io
import re
from pathlib import Path

# A German-locale Excel export -- semicolon delimiters, comma decimals,
# dotted thousands separators -- is the single most common real input to
# this layer and the one most likely to be silently mis-parsed: "1.234,5"
# read as 1.234 is a plausible-looking number, not an error. Locale is
# therefore detected per column from the values, never assumed.
_DECIMAL_COMMA_RE = re.compile(r"^-?\d{1,3}(\.\d{3})*(,\d+)?$|^-?\d+,\d+$")
_DECIMAL_DOT_RE = re.compile(r"^-?\d{1,3}(,\d{3})*(\.\d+)?$|^-?\d+\.\d+$")
_BLANK_RE = re.compile(r"^(n/?a|na|null|none|nd|n\.a\.|-|--|\.)$", re.IGNORECASE)

BOOL_TRUE = {"yes", "y", "true", "ja", "wahr", "1", "x", "t"}
BOOL_FALSE = {"no", "n", "false", "nein", "falsch", "0", "f"}

_DELIMITERS = (";", ",", "\t", "|")

TABLE_SUFFIXES = {".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".xls"}


def is_blank(value: object) -> bool:
    if value is None:
        return True
    s = str(value).strip()
    return s == "" or bool(_BLANK_RE.match(s))


def sniff_delimiter(text: str) -> str:
    """Picks the delimiter that yields the most consistent column count
    across the first few lines, rather than simply the most frequent
    character -- a free-text column full of commas otherwise wins over the
    semicolons actually separating the fields."""
    lines = [ln for ln in text.splitlines()[:20] if ln.strip()]
    if not lines:
        return ","
    best, best_score = ",", -1.0
    for delim in _DELIMITERS:
        counts = [len(next(csv.reader([ln], delimiter=delim))) for ln in lines]
        if max(counts) < 2:
            continue
        consistent = sum(1 for c in counts if c == counts[0]) / len(counts)
        score = consistent * 10 + counts[0]
        if score > best_score:
            best, best_score = delim, score
    return best


def parse_delimited(text: str, delimiter: str | None = None) -> list[list[str]]:
    if text.startswith("﻿"):
        text = text[1:]
    delim = delimiter or sniff_delimiter(text)
    rows = [[(cell or "").strip() for cell in row] for row in csv.reader(io.StringIO(text), delimiter=delim)]
    return [r for r in rows if any(cell != "" for cell in r)]


def _parse_xlsx(path: Path) -> list[list[str]]:
    """Reads the first worksheet. openpyxl is already a dependency of this
    codebase (arp/ingestion/local_files.py parses xlsx disclosures with
    it), which is why Excel support here needs no new package and -- unlike
    the browser prototype this replaces -- no script loaded from a CDN."""
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        rows: list[list[str]] = []
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else str(c).strip() for c in row]
            if any(cells):
                rows.append(cells)
        return rows
    finally:
        wb.close()


def load_table(path: Path | str) -> list[list[str]]:
    """Any supported tabular file -> a rectangular matrix of strings.
    Everything downstream types the values itself, so nothing is
    interpreted here beyond 'this cell held this text'."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix not in TABLE_SUFFIXES:
        raise ValueError(f"Unsupported table format: {suffix or p.name}. Expected one of {sorted(TABLE_SUFFIXES)}.")
    if suffix in (".xlsx", ".xlsm", ".xls"):
        matrix = _parse_xlsx(p)
    else:
        matrix = parse_delimited(p.read_text(encoding="utf-8-sig", errors="replace"))
    if not matrix:
        raise ValueError(f"No rows found in {p.name}.")
    width = max(len(r) for r in matrix)
    return [r + [""] * (width - len(r)) for r in matrix]


def detect_decimal_comma(values: list[str]) -> bool:
    comma = sum(1 for v in values if _DECIMAL_COMMA_RE.match(v.strip()) and "," in v)
    dot = sum(1 for v in values if _DECIMAL_DOT_RE.match(v.strip()) and "." in v)
    return comma > dot


def to_number(value: object, decimal_comma: bool = False) -> float | None:
    if is_blank(value):
        return None
    s = str(value).strip().replace(" ", "").replace(" ", "")
    s = s.rstrip("%")
    if decimal_comma:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "") if re.match(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$", s) else s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def to_bool(value: object) -> int | None:
    if is_blank(value):
        return None
    s = str(value).strip().lower()
    if s in BOOL_TRUE:
        return 1
    if s in BOOL_FALSE:
        return 0
    return None
