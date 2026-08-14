from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from arp.schemas.portfolio import SecurityRef, SecurityResolution


@dataclass
class SecurityMaster:
    """A user-supplied issuer reference table -- the same role a licensed
    security master (e.g. an OpenFIGI/Bloomberg feed) plays in production.
    Never fetched or fabricated by this system, same as every other
    external reference dataset this codebase integrates (OECD ICIO,
    NACE/NAICS/SIC crosswalks, fund holdings)."""

    isin_to_company_id: dict[str, str]
    company_names: dict[str, str]  # company_id -> canonical name, for the fuzzy fallback


def resolve_security(security: SecurityRef, master: SecurityMaster, confidence_review_threshold: float) -> SecurityResolution:
    """Resolves one security's issuer to a company_id.

    Path 1 (exact): the security's ISIN matches the reference table
    directly -- confidence 1.0, never reviewed.

    Path 2 (fuzzy fallback): no ISIN, or an ISIN the table doesn't
    recognize (e.g. a typo in the feed) -- falls back to a name similarity
    match against the table's known issuer names. Anything below
    `confidence_review_threshold` is flagged `needs_review` rather than
    auto-applied, because a wrong issuer match silently corrupts every
    euro figure computed downstream of it (see aggregation.py).
    """
    if security.isin and security.isin in master.isin_to_company_id:
        return SecurityResolution(
            security_id=security.security_id,
            company_id=master.isin_to_company_id[security.isin],
            confidence=1.0,
            method="isin_exact",
            needs_review=False,
        )

    best_company_id: str | None = None
    best_score = 0.0
    for company_id, name in master.company_names.items():
        score = SequenceMatcher(None, security.name.lower().strip(), name.lower().strip()).ratio()
        if score > best_score:
            best_score = score
            best_company_id = company_id

    if best_company_id is None:
        return SecurityResolution(security_id=security.security_id, company_id=None, confidence=0.0, method="name_fuzzy", needs_review=True)

    return SecurityResolution(
        security_id=security.security_id,
        company_id=best_company_id,
        confidence=best_score,
        method="name_fuzzy",
        needs_review=best_score < confidence_review_threshold,
    )


def resolve_all(securities: list[SecurityRef], master: SecurityMaster, confidence_review_threshold: float) -> list[SecurityResolution]:
    return [resolve_security(s, master, confidence_review_threshold) for s in securities]
