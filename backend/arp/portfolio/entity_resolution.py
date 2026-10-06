from __future__ import annotations

from dataclasses import dataclass

from arp.schemas.portfolio import SecurityRef, SecurityResolution


@dataclass
class SecurityMaster:
    """A user-supplied issuer reference table -- the same role a licensed
    security master (e.g. an OpenFIGI/Bloomberg feed) plays in production.
    Never fetched or fabricated by this system, same as every other
    external reference dataset this codebase integrates (OECD ICIO,
    NACE/NAICS/SIC crosswalks, fund holdings)."""

    isin_to_company_id: dict[str, str]


def resolve_security(security: SecurityRef, master: SecurityMaster) -> SecurityResolution:
    """Resolves one security's issuer by exact ISIN match against the master,
    or leaves it unresolved (`needs_review`): a name is never matched, because
    a wrong issuer silently corrupts every euro figure computed downstream of
    it (see aggregation.py). Fix an unresolved security in the master."""
    company_id = master.isin_to_company_id.get(security.isin or "")
    return SecurityResolution(
        security_id=security.security_id,
        company_id=company_id,
        confidence=1.0 if company_id else 0.0,
        method="isin_exact",
        needs_review=company_id is None,
    )


def resolve_all(securities: list[SecurityRef], master: SecurityMaster) -> list[SecurityResolution]:
    return [resolve_security(s, master) for s in securities]
