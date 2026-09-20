from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from arp.schemas.common import CompanyRef


@dataclass
class ResolvedEntity:
    name: str
    company_id: str | None
    confidence: float
    method: str  # "exact" | "fuzzy" | "unresolved"


def _normalize(name: str) -> str:
    return name.strip().lower()


def resolve_entity_name(name: str, companies: list[CompanyRef], confidence_threshold: float = 0.75) -> ResolvedEntity:
    """Resolves one free-text entity name (a GDELT/EDGAR-reported filer
    name, or a company name the LLM identified in a claim) to a
    `company_id` in the supplied universe.

    Mirrors `portfolio/entity_resolution.py::resolve_security`'s
    exact-then-fuzzy-fallback shape (there: ISIN exact, then
    `difflib.SequenceMatcher` name fuzzy match) rather than inventing a
    new matching approach -- the input shape differs (free text vs. a
    `SecurityRef`), so this isn't a direct reuse, but the matching
    discipline -- exact match trusted outright, fuzzy match only above a
    confidence floor, otherwise left unresolved rather than guessed -- is
    the same.
    """
    normalized = _normalize(name)
    if not normalized:
        return ResolvedEntity(name=name, company_id=None, confidence=0.0, method="unresolved")

    for company in companies:
        if _normalize(company.name) == normalized or (company.ticker and _normalize(company.ticker) == normalized):
            return ResolvedEntity(name=name, company_id=company.company_id, confidence=1.0, method="exact")

    best_company_id: str | None = None
    best_score = 0.0
    for company in companies:
        score = SequenceMatcher(None, normalized, _normalize(company.name)).ratio()
        if score > best_score:
            best_score = score
            best_company_id = company.company_id

    if best_company_id is not None and best_score >= confidence_threshold:
        return ResolvedEntity(name=name, company_id=best_company_id, confidence=best_score, method="fuzzy")
    return ResolvedEntity(name=name, company_id=None, confidence=best_score, method="unresolved")


def resolve_mention_companies(
    entity_names: list[str], companies: list[CompanyRef], confidence_threshold: float = 0.75
) -> list[str]:
    """Resolves a list of free-text entity names to the distinct
    `company_id`s in the universe they matched -- unresolved/low-confidence
    names are dropped, not guessed, so a mention with no recognizable
    universe company simply contributes no company_ids rather than a
    wrong one."""
    resolved = (resolve_entity_name(name, companies, confidence_threshold) for name in entity_names)
    return sorted({r.company_id for r in resolved if r.company_id is not None})
