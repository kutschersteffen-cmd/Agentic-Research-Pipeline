"""Locale-aware number parsing: language from stop words, decimal mark from language or neighbours."""

from __future__ import annotations

import csv
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Literal

Decimal = Literal["point", "comma"]

_TABLES = Path(__file__).parent / "tables"
MIN_HITS = 5
_SPACES = " \u00a0\u202f\u2009"
_JUNK = re.compile(rf"[^\d.,\-−'{_SPACES}]")
_SEP = re.compile(rf"['{_SPACES}]")
_GROUPED = {",": re.compile(r"\d{1,3}(,\d{3})+"), ".": re.compile(r"\d{1,3}(\.\d{3})+")}
_WORD = re.compile(r"[^\W\d_]+")
_NUMBER = re.compile(r"\d[\d.,]*\d")


@lru_cache(maxsize=1)
def _locale_table() -> tuple[dict[str, str], dict[str, str]]:
    with open(_TABLES / "locale_v1.csv", encoding="utf8", newline="") as f:
        rows = list(csv.DictReader(f))
    return {r["word"]: r["language"] for r in rows}, {r["language"]: r["decimal"] for r in rows}


def detect_language(text: str) -> str | None:
    words, _ = _locale_table()
    hits = Counter(words[w] for w in _WORD.findall(text.casefold()) if w in words)
    if not hits:
        return None
    lang, n = hits.most_common(1)[0]
    return lang if n >= MIN_HITS else None


def decimal_for(language: str | None) -> Decimal | None:
    return _locale_table()[1].get(language or "")  # type: ignore[return-value]


def _thousands_shaped(s: str, sep: str) -> bool:
    return bool(_GROUPED[sep].fullmatch(s)) and s[0] != "0"


def _implied(s: str) -> Decimal | None:
    """The decimal mark a digits-and-separators string proves, or None when it could be either."""
    if "," in s and "." in s:
        return "comma" if s.rfind(",") > s.rfind(".") else "point"
    for sep, mark, other in ((",", "comma", "point"), (".", "point", "comma")):
        if sep in s:
            if s.count(sep) > 1:
                return other if _thousands_shaped(s, sep) else None
            return None if _thousands_shaped(s, sep) else mark
    return None


def context_decimal(numbers: list[str]) -> Decimal | None:
    votes = Counter(m for n in numbers if (m := _implied(_SEP.sub("", n.strip().lstrip("(-−").rstrip(")%")))))
    top = votes.most_common(2)
    if not top or (len(top) == 2 and top[0][1] == top[1][1]):
        return None
    return top[0][0]


def citation_decimal(citations, documents_by_id: dict) -> Decimal | None:
    """The decimal mark a value reads with: the one its cited table's own numbers prove (grounded
    citations carry table_ref), else the cited documents' shared decimal (None if they disagree or are unknown)."""
    docs = {d.decimal if (d := documents_by_id.get(c.doc_id)) else None for c in citations}
    shared = docs.pop() if len(docs) == 1 else None
    for c in citations:
        doc = documents_by_id.get(c.doc_id) if c.table_ref else None
        t = next((t for t in doc.table_spans if t.table_id == c.table_ref.table_id), None) if doc else None
        if t:
            return context_decimal(_NUMBER.findall(doc.full_text[t.char_start : t.char_end])) or shared
    return shared


def parse_number(text: str, decimal: Decimal | None = None) -> tuple[float | None, bool]:
    """(value, ambiguous). "1,234" / "1.234" may be a thousands group or a decimal: `decimal` decides,
    and with no decision it parses as "point" and says so."""
    s = text.strip()
    neg = s.startswith("(") and s.endswith(")")
    s = _SEP.sub("", _JUNK.sub("", s))
    if s[:1] in ("-", "−") and s:
        neg, s = True, s[1:]
    if not s or not s[0].isdigit() or not s[-1].isdigit():
        return None, False
    ambiguous = False
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        if s.count(dec) > 1 or not _thousands_shaped(s[: s.rfind(dec)], thou):
            return None, False
        s = s.replace(thou, "").replace(dec, ".")
    else:
        for sep in (",", "."):
            if sep not in s:
                continue
            if s.count(sep) > 1:
                if not _thousands_shaped(s, sep):
                    return None, False
                s = s.replace(sep, "")
            elif _thousands_shaped(s, sep):
                mark = decimal or "point"
                ambiguous = decimal is None
                s = s.replace(sep, "") if (sep == ",") == (mark == "point") else s.replace(sep, ".")
            else:
                s = s.replace(sep, ".")
            break
    try:
        v = float(s)
    except ValueError:
        return None, False
    return (-v if neg else v), ambiguous
