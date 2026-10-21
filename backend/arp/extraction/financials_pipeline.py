from __future__ import annotations

import logging
import re

from arp.config import Settings
from arp.extraction.financials_graph import extract_company_financials
from arp.extraction.pre_steps import prepare_company
from arp.ingestion.registry import DocumentSourceRegistry
from arp.ingestion.xbrl import CAPEX_TAGS, RND_TAGS, XbrlFactSource
from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.batch_runner import run_company_batch
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd
from arp.orchestration.job_manager import JobManager
from arp.schemas.common import CompanyRef
from arp.schemas.financials import CompanyFinancialsRecord
from arp.schemas.spend import AmountMetric
from arp.storage.run_store import RunStore

logger = logging.getLogger(__name__)


class FinancialsExtractionResult:
    def __init__(self, record: CompanyFinancialsRecord, usage: LLMUsage, cost_usd: float) -> None:
        self.record = record
        self.usage = usage
        self.cost_usd = cost_usd


_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def _fiscal_year(fiscal_period: str | None) -> int | None:
    """The last four-digit year in the LLM's free-text period ("FY2024", "year ended 31 Dec 2024")."""
    years = _YEAR.findall(fiscal_period or "")
    return int(years[-1]) if years else None


async def _overlay_xbrl_facts(
    record: CompanyFinancialsRecord, company: CompanyRef, xbrl_source: XbrlFactSource
) -> CompanyFinancialsRecord:
    """Path 0 ahead of the LLM pipeline's own capex/rnd totals: if SEC's
    structured XBRL data has a figure for this EDGAR filer, it replaces
    the LLM-extracted total outright -- a hard, machine-tagged fact from
    the company's own filing is strictly more trustworthy than an LLM's
    read of prose, the same precedence the revenue/CapEx catalogue cascade
    (arp/research/revenue_exposure/resolver.py) already applies. Only the
    scalar `total` is replaced; `description`/`categories` (XBRL has no
    plain-language breakdown) and everything else the LLM pass produced
    (segments, needs_review from other reasons) are left untouched.
    Only the record's own fiscal year is used: with no year, nothing is replaced.
    """
    fiscal_year = _fiscal_year(record.fiscal_period)
    if fiscal_year is None:
        return record
    cik = await xbrl_source.resolve_cik(company.cik, company.ticker)
    if not cik:
        return record
    facts_json = await xbrl_source.fetch_company_facts(cik)
    if facts_json is None:
        return record

    updates: dict = {}
    for field, tags in (("capex", CAPEX_TAGS), ("rnd", RND_TAGS)):
        fact = XbrlFactSource.fact_for_tags(facts_json, tags, fiscal_year=fiscal_year)
        if fact is None:
            continue
        updates[field] = getattr(record, field).model_copy(
            update={
                "total": AmountMetric(
                    value=fact.value,
                    raw_value_text=f"{fact.value:,.0f} {fact.unit} (SEC XBRL, us-gaap:{fact.tag})",
                    citations=[fact.as_citation(cik)],
                    grounded=True,
                ),
                "confidence": 1.0,
                "grounded": True,
            }
        )
    if not updates:
        return record
    return record.model_copy(update=updates)


async def _extract_company_financials(
    company: CompanyRef,
    *,
    registry: DocumentSourceRegistry,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    settings: Settings,
    xbrl_source: XbrlFactSource | None = None,
) -> FinancialsExtractionResult:
    documents = await registry.fetch_all(company)
    record, usages = await extract_company_financials(
        company,
        documents=documents,
        llm=llm,
        verifier_llm=verifier_llm,
        settings=settings,
        fuzzy_threshold=settings.grounding_fuzzy_threshold,
        confidence_review_threshold=settings.confidence_review_threshold,
    )
    if xbrl_source is not None and settings.xbrl_facts_enabled:
        record = await _overlay_xbrl_facts(record, company, xbrl_source)
    cost = sum(estimate_cost_usd(u.model or settings.llm_model, u) for u in usages)
    return FinancialsExtractionResult(record, combine_usage(*usages) if usages else LLMUsage(), cost)


def create_financials_extraction_run(companies: list[CompanyRef], settings: Settings, run_store: RunStore) -> str:
    job_manager = JobManager(run_store)
    manifest = job_manager.create_run(
        "financials",
        {**({"batch": True} if settings.llm_batch else {})},
        len(companies),
        model=settings.llm_model,
        verifier_model=settings.llm_verifier_model,
        companies=companies,
    )
    return manifest.run_id


async def execute_financials_extraction_run(
    run_id: str,
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
    xbrl_source: XbrlFactSource | None = None,
) -> str:
    """Orchestrates combined segments/CapEx/R&D extraction (one evidence
    gather + one extractor call + one independent verifier call per
    company -> programmatic grounding check -> aggregation) across the
    whole company universe, checkpointed and resumable, against an
    already-created run (see create_financials_extraction_run)."""

    async def _worker(company: CompanyRef) -> FinancialsExtractionResult:
        company = await prepare_company(company, settings=settings, llm=llm, registry=registry)
        result = await _extract_company_financials(
            company, registry=registry, llm=llm, verifier_llm=verifier_llm, settings=settings, xbrl_source=xbrl_source
        )
        result.record.run_id = run_id
        return result

    await run_company_batch(
        run_id,
        companies,
        run_store=run_store,
        worker=_worker,
        result_to_json=lambda r: r.record.model_dump(mode="json"),
        review_items=lambda c, r: [(c.company_id, r.record.model_dump(mode="json"))] if r.record.needs_review else [],
        cost_usd=lambda r: r.cost_usd,
        concurrency=settings.max_concurrent_llm_calls,
    )
    return run_id


async def run_financials_extraction(
    companies: list[CompanyRef],
    *,
    llm: LLMClient,
    verifier_llm: LLMClient | None = None,
    registry: DocumentSourceRegistry,
    settings: Settings,
    run_store: RunStore,
    xbrl_source: XbrlFactSource | None = None,
) -> str:
    """Convenience wrapper (create + execute in one call) for synchronous
    callers such as the CLI, where blocking until completion is expected."""
    run_id = create_financials_extraction_run(companies, settings, run_store)
    return await execute_financials_extraction_run(
        run_id,
        companies,
        llm=llm,
        verifier_llm=verifier_llm,
        registry=registry,
        settings=settings,
        run_store=run_store,
        xbrl_source=xbrl_source,
    )
