"""Narrow a company universe to a taxonomy's sector codes before discovery and theme runs (theme-funnel spec,
amended 2026-11-03): match at ISIC division (first 2 digits), which NACE shares; companies without a known
ISIC/NACE code are kept."""

from __future__ import annotations

from arp.schemas.common import CompanyRef
from arp.schemas.thematic import ThemeDefinition


def _division(code: str | None) -> str | None:
    digits = "".join(ch for ch in code or "" if ch.isdigit())
    return digits[:2] if len(digits) >= 2 else None


def taxonomy_divisions(theme: ThemeDefinition) -> set[str]:
    # shortcut: core_isic_codes only until PR #325 lands; then add ActivityDefinition.sector_codes (system ISIC/NACE)
    return {d for a in theme.activities for d in map(_division, a.core_isic_codes) if d}


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
