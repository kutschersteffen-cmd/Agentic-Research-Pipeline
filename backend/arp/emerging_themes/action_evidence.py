from __future__ import annotations

from arp.ingestion.xbrl import XbrlFactSource
from arp.schemas.common import CompanyRef
from arp.schemas.emerging_themes import CompanyActionEvidence


async def check_company_action_evidence(
    company: CompanyRef, xbrl_source: XbrlFactSource
) -> CompanyActionEvidence | None:
    """Roadmap P3's structured-financials cross-check for one company:
    resolves a CIK and looks up its year-over-year CapEx/R&D movement via
    SEC's structured XBRL data, degrading gracefully to `None` -- never
    raising -- exactly like `financials_pipeline.py::_overlay_xbrl_facts`
    does for a company with no ticker/CIK resolvable or no XBRL facts at
    all. Most companies in a universe (non-US filers, thin disclosers)
    will legitimately return `None` here; that is why this is attached to
    a candidate as supporting evidence, never used as a promotion gate.
    """
    cik = await xbrl_source.resolve_cik(company.cik, company.ticker)
    if not cik:
        return None
    trend = await xbrl_source.fetch_capex_rnd_trend(company.company_id, cik)
    if trend is None:
        return None
    if trend.capex is None and trend.rnd is None:
        return None
    return CompanyActionEvidence(
        company_id=company.company_id,
        cik=cik,
        capex_pct_change=trend.capex.pct_change if trend.capex else None,
        rnd_pct_change=trend.rnd.pct_change if trend.rnd else None,
    )
