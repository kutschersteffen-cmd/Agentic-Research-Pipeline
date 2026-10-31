"""Keyword rules that tag an outline heading, e.g. "EU Taxonomy" -> eu_taxonomy."""

from __future__ import annotations

# tag -> words, matched as lower-cased substrings of the heading title
_RULES: dict[str, tuple[str, ...]] = {
    "eu_taxonomy": ("taxonom",),
    "climate_targets": ("target", "net zero", "net-zero", "decarboni", "ziel"),
    "transition_plan": ("transition", "übergang"),
    "ghg_emissions": ("ghg", "emission", "greenhouse", "scope 1", "scope 3", "treibhausgas"),
    "governance": ("governance", "board", "supervisory", "aufsichtsrat", "vorstand"),
    "remuneration": ("remuneration", "compensation", "vergütung"),
    "biodiversity": ("biodiversity", "ecosystem", "biodiversität"),
    "water": ("water", "marine", "wasser"),
    "workforce": ("workforce", "employee", "mitarbeit", "beschäftigt"),
}


def section_tags_for(title: str) -> list[str]:
    lowered = title.lower()
    return [tag for tag, words in _RULES.items() if any(w in lowered for w in words)]
