"""Word rules that name a table's kind from its caption, heading path and column headers."""

from __future__ import annotations

# (kind, all_of, any_of, none_of), first match wins. Words match lower-cased substrings of
# caption + heading path + column headers; none_of is checked against caption + heading path only.
_RULES: list[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = [
    ("eu_taxonomy_capex", ("taxonom",), ("capex", "capital expenditure", "investitionsausgaben"), ("opex", "turnover", "umsatz")),
    ("eu_taxonomy_opex", ("taxonom",), ("opex", "operating expenditure", "betriebsausgaben"), ("turnover", "umsatz")),
    ("eu_taxonomy_turnover", ("taxonom",), ("turnover", "revenue", "umsatz"), ()),
    ("ghg_targets", ("target",), ("ghg", "emission", "co2", "scope 1", "scope 3", "net zero", "net-zero"), ()),
    ("ghg_emissions", (), ("scope 1", "scope 2", "scope 3", "ghg emission", "greenhouse gas", "co2e", "co2 emission"), ()),
    ("energy", (), ("energy consumption", "energy mix", "energieverbrauch", "mwh", "gwh"), ()),
    ("remuneration", (), ("remuneration", "vergütung", "executive compensation"), ()),
]


def table_kind(caption: str | None, heading_path: list[str], column_headers: list[str]) -> str | None:
    context = " ".join([caption or "", *heading_path]).lower()
    words = " ".join([context, *column_headers]).lower()
    for kind, all_of, any_of, none_of in _RULES:
        if all(w in words for w in all_of) and any(w in words for w in any_of) and not any(w in context for w in none_of):
            return kind
    return None
