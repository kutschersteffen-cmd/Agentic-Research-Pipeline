"""Narrow a company universe to a taxonomy's sector codes before discovery and theme runs (theme-funnel spec,
amended 2026-11-03): match at ISIC division (first 2 digits), which NACE shares; companies without a known
ISIC/NACE code are kept."""

from __future__ import annotations

from arp.research.indirect_exposure.nace import sector_nace2_codes
from arp.schemas.common import CompanyRef
from arp.schemas.thematic import ThemeDefinition


def _division(code: str | None) -> str | None:
    digits = "".join(ch for ch in code or "" if ch.isdigit())
    return digits[:2] if len(digits) >= 2 else None


def taxonomy_divisions(theme: ThemeDefinition) -> set[str]:
    codes = [
        *(c for a in theme.activities for s in a.core_sectors for c in sector_nace2_codes(s)),
        *(s.code for a in theme.activities for s in a.sector_codes if s.system in ("ISIC", "NACE")),
    ]
    return {d for d in map(_division, codes) if d}


def narrow_universe(
    companies: list[CompanyRef], theme: ThemeDefinition, keep: set[str] = frozenset()
) -> tuple[list[CompanyRef], list[dict]]:
    wanted = taxonomy_divisions(theme)
    kept: list[CompanyRef] = []
    dropped: list[dict] = []
    for c in companies:
        own = {d for d in (_division(c.isic_code), _division(c.nace_code)) if d}
        if not wanted or not own or own & wanted or c.company_id in keep:
            kept.append(c)
            continue
        dropped.append({
            "company_id": c.company_id, "name": c.name, "isic_code": c.isic_code, "nace_code": c.nace_code,
            "reason": f"no sector match (company {', '.join(sorted(own))}, taxonomy {', '.join(sorted(wanted))})",
        })
    return kept, dropped
