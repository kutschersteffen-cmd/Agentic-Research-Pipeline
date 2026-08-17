from __future__ import annotations

from arp.ingestion.parsing import chunk_document
from arp.llm.base import LLMClient, LLMUsage
from arp.retrieval.select_evidence import select_relevant_chunks
from arp.schemas.common import CompanyRef, DocumentChunk, SourceDocument
from arp.schemas.transition_plan import CategoryBreakdown, IndicatorCategory, TransitionPlanAssessmentRecord, Verdict, WalkOrTalk
from arp.transition_plan.basic_info_agent import format_basic_info, get_basic_company_info
from arp.transition_plan.indicator_graph import assess_one_indicator
from arp.transition_plan.indicators import load_indicators

_BASIC_INFO_QUERY = "company name industry sector headquarters location about us overview"
_BASIC_INFO_MAX_CHUNKS = 8


def _summarize(company: CompanyRef, run_id: str, record_fields: dict) -> TransitionPlanAssessmentRecord:
    indicators = record_fields.pop("indicators")
    disclosed = [a for a in indicators if a.verdict == Verdict.YES]
    answered = [a for a in indicators if a.verdict != Verdict.NA]

    walk_total = sum(1 for a in indicators if a.walk_or_talk == WalkOrTalk.WALK)
    talk_total = sum(1 for a in indicators if a.walk_or_talk == WalkOrTalk.TALK)
    walk_disclosed = sum(1 for a in disclosed if a.walk_or_talk == WalkOrTalk.WALK)
    talk_disclosed = sum(1 for a in disclosed if a.walk_or_talk == WalkOrTalk.TALK)

    by_category = []
    for cat in IndicatorCategory:
        cat_indicators = [a for a in indicators if a.category == cat]
        by_category.append(
            CategoryBreakdown(
                category=cat,
                disclosed_count=sum(1 for a in cat_indicators if a.verdict == Verdict.YES),
                total_count=len(cat_indicators),
            )
        )

    overall_confidence = sum(a.confidence for a in answered) / len(answered) if answered else 0.0

    return TransitionPlanAssessmentRecord(
        company_id=company.company_id,
        ticker=company.ticker,
        name=company.name,
        run_id=run_id,
        indicators=indicators,
        disclosed_count=len(disclosed),
        walk_disclosed_count=walk_disclosed,
        walk_total_count=walk_total,
        talk_disclosed_count=talk_disclosed,
        talk_total_count=talk_total,
        by_category=by_category,
        overall_confidence=overall_confidence,
        needs_review=any(a.needs_review for a in indicators),
        **record_fields,
    )


async def assess_company_transition_plan(
    company: CompanyRef,
    *,
    documents: list[SourceDocument],
    llm: LLMClient,
    fuzzy_threshold: float,
    run_id: str = "",
) -> tuple[TransitionPlanAssessmentRecord, list[LLMUsage]]:
    """Runs the full 64-indicator assessment for one company: chunk each
    document once, resolve basic company info once (reused as `{basic_info}`
    in every indicator prompt, exactly like the paper's reference tool),
    then answer each of the 64 indicators in turn -- sequential per company,
    the same shape as arp/extraction/pipeline.py's per-field loop; batch-
    level concurrency (see pipeline.py) is what keeps a large universe run
    fast, not intra-company parallelism.
    """
    documents_by_id = {d.doc_id: d for d in documents}
    all_chunks: list[DocumentChunk] = []
    for doc in documents:
        all_chunks.extend(chunk_document(doc))

    usages: list[LLMUsage] = []
    company_sector = company.sector
    company_location = None

    basic_info_text = f" - Company name: {company.name}"
    if all_chunks:
        basic_chunks = select_relevant_chunks(
            all_chunks, [_BASIC_INFO_QUERY], max_chunks=_BASIC_INFO_MAX_CHUNKS, require_hit=False, fallback_to_all=True
        )
        if basic_chunks:
            info, usage = await get_basic_company_info(basic_chunks, llm)
            usages.append(usage)
            basic_info_text = format_basic_info(info)
            company_sector = company_sector or info.company_sector
            company_location = info.company_location

    assessments = []
    for indicator in load_indicators():
        assessment, indicator_usages = await assess_one_indicator(
            company.name,
            basic_info_text,
            indicator,
            all_chunks=all_chunks,
            documents_by_id=documents_by_id,
            llm=llm,
            fuzzy_threshold=fuzzy_threshold,
        )
        assessments.append(assessment)
        usages.extend(indicator_usages)

    record = _summarize(
        company,
        run_id,
        {"indicators": assessments, "company_sector": company_sector, "company_location": company_location},
    )
    return record, usages
