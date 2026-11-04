from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChecklistItem:
    key: str
    question: str
    keywords: list[str]


AUTHORITY_CHECKLIST: list[ChecklistItem] = [
    ChecklistItem("theme_description", "A qualitative description of what the theme covers.", ["theme", "covers", "objective", "purpose", "description"]),
    ChecklistItem("activities", "The concrete business activities that make up the theme.", ["activity", "activities", "manufacture", "production", "installation", "operation", "services"]),
    ChecklistItem("boundaries", "Explicit include / exclude rules.", ["include", "includes", "exclude", "excludes", "excluded", "scope", "does not", "not covered"]),
    ChecklistItem("technologies", "The technologies the theme rests on.", ["technology", "technologies", "equipment", "process", "system"]),
    ChecklistItem("definitions", "Defined terms.", ["means", "defined", "definition", "refers", "term"]),
    ChecklistItem("sector_codes", "GICS, ISIC or NACE codes the source names.", ["NACE", "ISIC", "GICS", "NAICS", "SIC", "code", "codes"]),
    ChecklistItem("value_chain", "Upstream and enabling activities: components, materials, bills of materials, equipment.", ["component", "components", "materials", "bill", "supply", "upstream", "equipment"]),
    ChecklistItem("thresholds", "Eligibility thresholds (revenue share, capex share, pure-play rules).", ["threshold", "revenue", "capex", "share", "percent", "%", "least", "pure-play"]),
]
