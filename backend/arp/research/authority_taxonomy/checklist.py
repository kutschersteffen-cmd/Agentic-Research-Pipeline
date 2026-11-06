from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChecklistItem:
    key: str
    question: str
    keywords: list[str]


AUTHORITY_CHECKLIST: list[ChecklistItem] = [
    ChecklistItem("theme_description", "A qualitative description of what the theme covers.", ["theme", "covers", "objective", "purpose", "description"]),
    ChecklistItem("activities", "The concrete business activities that make up the theme: when a heading covers several products or equipment types, one entry per product or equipment type its description names, kept in the source's own grouping, instead of one entry for the heading.", ["activity", "activities", "manufacture", "production", "installation", "operation", "services"]),
    ChecklistItem("boundaries", "Explicit include / exclude rules.", ["include", "includes", "exclude", "excludes", "excluded", "scope", "does not", "not covered"]),
    ChecklistItem("technologies", "The technologies the theme rests on.", ["technology", "technologies", "equipment", "process", "system"]),
    ChecklistItem("definitions", "Defined terms.", ["means", "defined", "definition", "refers", "term"]),
    ChecklistItem("sector_codes", "GICS, ISIC or NACE codes the source names.", ["NACE", "ISIC", "GICS", "NAICS", "SIC", "code", "codes"]),
    ChecklistItem("value_chain", "Upstream and enabling activities: components, materials, bills of materials, equipment.", ["component", "components", "materials", "bill", "supply", "upstream", "equipment"]),
    ChecklistItem("thresholds", "Eligibility thresholds (revenue share, capex share, pure-play rules).", ["threshold", "revenue", "capex", "share", "percent", "%", "least", "pure-play"]),
]

# Layer 1 of taxonomy-from-stocks: an index methodology's stated construction rules.
INDEX_RULES_CHECKLIST: list[ChecklistItem] = [
    ChecklistItem("eligibility", "Stated eligibility rules: minimum market capitalisation, liquidity, revenue or exposure share, listing, sector or discretionary exclusions.", ["eligible", "eligibility", "minimum", "capitalisation", "capitalization", "liquidity", "traded", "exclude", "excluded", "exclusion", "discretion", "committee", "revenue", "exposure", "listed"]),
    ChecklistItem("selection", "Stated selection rules: how many constituents and how they are chosen.", ["select", "selected", "selection", "constituents", "largest", "number", "top", "ranked", "comprise", "comprises"]),
    ChecklistItem("weighting", "Stated weighting scheme: market-capitalisation, equal or other weighting.", ["weight", "weighted", "weighting", "weights", "equal", "equally"]),
    ChecklistItem("caps", "Stated weight caps: single-stock caps, 5/10/40 rules, group caps.", ["cap", "capped", "capping", "exceed", "maximum", "limit", "limited", "5/10/40"]),
    ChecklistItem("rebalance", "Stated review and rebalancing frequency.", ["review", "reviewed", "rebalance", "rebalanced", "rebalancing", "reconstitution", "monthly", "quarterly", "annual", "annually", "semi-annual", "semi-annually"]),
]
