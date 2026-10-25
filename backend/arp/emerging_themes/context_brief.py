"""Step 1's context brief: why now, the early evidence, the affected sectors (spec theme-context-brief).

Everything countable is computed here from the candidate's own evidence; one model call words the
sentences and activities, and `_check_draft` drops whatever does not cite that evidence."""

from __future__ import annotations

import csv
import logging
import re
from functools import cache
from pathlib import Path

from pydantic import BaseModel

from arp.emerging_themes.synthesis import independent_source_count
from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.common import CompanyRef
from arp.schemas.emerging_themes import (
    ActionType,
    ActivityGroup,
    BriefActivities,
    BriefCompany,
    BriefFacts,
    BriefFinancialsEvidence,
    BriefQuoteEvidence,
    BriefSector,
    BriefStatement,
    CompanyActivity,
    ContextBrief,
    ContradictionType,
    EmergingThemeCandidate,
    ExtractedTag,
    MentionCitation,
    RawMention,
)

logger = logging.getLogger(__name__)

_ISIC_CSV = Path(__file__).parent / "reference" / "isic4_divisions.csv"
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_ACTIONS = ("capex", "hiring", "orders", "capacity", "partnership")

_SYSTEM_PROMPT = """\
You write the context brief for a candidate investment theme, using only the numbered evidence items given.

Return:
- why_now: short sentences on what changed recently that makes this theme visible now.
- early_evidence: short sentences on what the evidence actually says, including any counter-evidence.
- by_company: for each listed company without an industry code, one short phrase describing the activity \
the evidence shows it doing, citing the items that cover that company.
- groups: activities shared by two or more of those companies, each with the company ids that share it.

Every sentence and phrase cites the ids (e.g. "E3") of the items it rests on. Write short, neutral, \
factual sentences. No promotional language, no forecasts, and no figure the cited quotes do not state. \
Do not restate dates, source counts or scores: they are shown separately. No outside knowledge."""


class _ContextBriefDraft(BaseModel):
    why_now: list[BriefStatement]
    early_evidence: list[BriefStatement]
    by_company: list[CompanyActivity]
    groups: list[ActivityGroup]


@cache
def isic_divisions() -> dict[str, str]:
    with _ISIC_CSV.open(encoding="utf-8") as f:
        return {row["division"]: row["title"] for row in csv.DictReader(f)}


def isic_division(code: str | None) -> str | None:
    division = (code or "")[:2]
    return division if division.isdigit() and division in isic_divisions() else None


def _citation_tag(citation: MentionCitation, member_tags: list[ExtractedTag]) -> ExtractedTag | None:
    return next((t for t in member_tags if t.grounded and t.mention_id == citation.mention_id and t.quote == citation.quote), None)


def _quote_item(kind: str, mention: RawMention, tag: ExtractedTag, company_ids: list[str]) -> BriefQuoteEvidence:
    return BriefQuoteEvidence(
        evidence_id="", kind=kind, mention_id=mention.mention_id, source_type=mention.source_type, title=mention.title,
        url=mention.url, published_at=mention.published_at, quote=tag.quote, action_type=tag.action_type,
        company_ids=company_ids,
    )


def _covers(item: BriefQuoteEvidence | BriefFinancialsEvidence, company_id: str) -> bool:
    return company_id in item.company_ids if isinstance(item, BriefQuoteEvidence) else item.company_id == company_id


def _evidence_pool(
    candidate: EmergingThemeCandidate, member_tags: list[ExtractedTag], mentions_by_id: dict[str, RawMention],
    company_ids_by_mention: dict[str, list[str]], unclassified: list[str],
) -> list[BriefQuoteEvidence | BriefFinancialsEvidence]:
    order = candidate.candidate_sectors_companies

    def companies_of(mention_id: str) -> list[str]:
        resolved = set(company_ids_by_mention.get(mention_id, []))
        return [c for c in order if c in resolved]

    def citation_items(kind: str, citations: list[MentionCitation], tags: list[ExtractedTag]) -> list[BriefQuoteEvidence]:
        items = []
        for citation in citations:
            mention, tag = mentions_by_id.get(citation.mention_id), _citation_tag(citation, tags)
            if mention is not None and tag is not None:
                items.append(_quote_item(kind, mention, tag, companies_of(mention.mention_id)))
        return items

    pool: list[BriefQuoteEvidence | BriefFinancialsEvidence] = citation_items("quote", candidate.corroborating_sources, member_tags)
    # One extra quote per uncovered company without ISIC, so each can get a cited activity line.
    uncovered = [c for c in unclassified if not any(_covers(item, c) for item in pool)]
    first_tags: dict[str, ExtractedTag] = {}
    for tag in member_tags:
        for company_id in uncovered:
            if company_id not in first_tags and tag.grounded and tag.mention_id in mentions_by_id and company_id in company_ids_by_mention.get(tag.mention_id, []):
                first_tags[company_id] = tag
    first_tag_ids = {t.tag_id for t in first_tags.values()}
    seen_mentions: set[str] = set()
    for tag in member_tags:
        if tag.tag_id in first_tag_ids and tag.mention_id not in seen_mentions:
            seen_mentions.add(tag.mention_id)
            pool.append(_quote_item("quote", mentions_by_id[tag.mention_id], tag, companies_of(tag.mention_id)))
    counter_tags = [t for t in member_tags if t.contradiction_type != ContradictionType.NONE]
    pool += citation_items("counter", candidate.contradiction_evidence, counter_tags)
    pool += [
        BriefFinancialsEvidence(evidence_id="", company_id=e.company_id, capex_pct_change=e.capex_pct_change, rnd_pct_change=e.rnd_pct_change)
        for e in candidate.xbrl_corroboration
    ]
    for n, item in enumerate(pool, start=1):
        item.evidence_id = f"E{n}"
    return pool


def _facts(candidate: EmergingThemeCandidate, member_tags: list[ExtractedTag], mentions_by_id: dict[str, RawMention], pool: list) -> BriefFacts:
    dates = [item.published_at[:10] for item in pool if isinstance(item, BriefQuoteEvidence) and item.published_at]
    return BriefFacts(
        first_seen=min(dates, default=None), last_seen=max(dates, default=None),
        independent_sources=independent_source_count(member_tags, mentions_by_id),
        company_count=len(candidate.candidate_sectors_companies),
        velocity=candidate.signal_velocity, breadth=candidate.breadth, persistence=candidate.persistence,
        novelty=candidate.novelty, materiality=candidate.materiality, contradiction=candidate.contradiction,
        action_counts={a: sum(1 for t in member_tags if t.action_type == ActionType(a)) for a in _ACTIONS},
    )


def _sectors(companies: list[BriefCompany], pool: list) -> list[BriefSector]:
    sectors = []
    for division in sorted({c.isic_division for c in companies if c.isic_division}):
        ids = [c.company_id for c in companies if c.isic_division == division]
        evidence_ids = [item.evidence_id for item in pool if any(_covers(item, c) for c in ids)]
        sectors.append(BriefSector(isic_division=division, label=isic_divisions()[division], company_ids=ids, evidence_ids=evidence_ids))
    return sorted(sectors, key=lambda s: -len(s.company_ids))  # stable: ties stay in division order


def _check_draft(draft: _ContextBriefDraft, pool: list, unclassified: list[str]) -> tuple[_ContextBriefDraft, list[str], int]:
    """Keeps only what cites the candidate's own evidence; returns (kept, unclassified ids, dropped count)."""
    rank = {item.evidence_id: n for n, item in enumerate(pool)}
    by_id = {item.evidence_id: item for item in pool}
    dropped = 0

    def in_pool_order(ids) -> list[str]:
        return sorted({i for i in ids if i in rank}, key=rank.__getitem__)

    def statements(raw: list[BriefStatement]) -> list[BriefStatement]:
        nonlocal dropped
        kept = []
        for s in raw:
            ids = in_pool_order(s.evidence_ids)
            quotes = [by_id[i].quote for i in ids if isinstance(by_id[i], BriefQuoteEvidence)]
            if not ids or any(not any(n in q for q in quotes) for n in _NUMBER.findall(s.text)):
                dropped += 1
                continue
            kept.append(BriefStatement(text=s.text, evidence_ids=ids))
        return kept

    lines: dict[str, CompanyActivity] = {}
    for line in draft.by_company:
        ids = in_pool_order(i for i in line.evidence_ids if i in by_id and _covers(by_id[i], line.company_id))
        if line.company_id not in unclassified or line.company_id in lines or not ids:
            dropped += 1
            continue
        lines[line.company_id] = CompanyActivity(company_id=line.company_id, activity=line.activity, evidence_ids=ids)

    groups = []
    for group in draft.groups:
        members = [c for c in unclassified if c in lines and c in group.company_ids]
        if len(members) < 2:
            dropped += 1
            continue
        groups.append(ActivityGroup(activity=group.activity, company_ids=members,
                                    evidence_ids=in_pool_order(i for c in members for i in lines[c].evidence_ids)))

    kept = _ContextBriefDraft(
        why_now=statements(draft.why_now), early_evidence=statements(draft.early_evidence),
        by_company=[lines[c] for c in unclassified if c in lines], groups=groups,
    )
    return kept, [c for c in unclassified if c not in lines], dropped


def _pct(fraction: float | None) -> str:
    """The SEC lookup stores a fraction (0.25 = +25%); the model reads it as the card shows it."""
    return "n/a" if fraction is None else f"{fraction * 100:+.1f}%"


def _prompt(candidate: EmergingThemeCandidate, pool: list, companies: list[BriefCompany], unclassified: list[str]) -> str:
    names = {c.company_id: c.name for c in companies}
    evidence = []
    for item in pool:
        if isinstance(item, BriefQuoteEvidence):
            label = "Counter-evidence" if item.kind == "counter" else "Quote"
            evidence.append(f'{item.evidence_id} [{label}, {item.action_type.value}, companies: {", ".join(item.company_ids) or "none"}] "{item.quote}"')
        else:
            evidence.append(f"{item.evidence_id} [SEC filings, company: {item.company_id}] CapEx change {_pct(item.capex_pct_change)}, R&D change {_pct(item.rnd_pct_change)}")
    unclassified_lines = [
        f"- {c} ({names[c]}): items {', '.join(i.evidence_id for i in pool if _covers(i, c)) or 'none'}" for c in unclassified
    ]
    return (
        f"Theme: {candidate.theme_name}\nDescription: {candidate.description}\n\n"
        "Evidence:\n" + "\n".join(evidence) + "\n\n"
        "Companies without an industry code:\n" + ("\n".join(unclassified_lines) or "none")
    )


async def build_context_brief(
    candidate: EmergingThemeCandidate, member_tags: list[ExtractedTag],
    mentions_by_id: dict[str, RawMention], company_ids_by_mention: dict[str, list[str]],
    companies_by_id: dict[str, CompanyRef], llm: LLMClient,
) -> tuple[ContextBrief, LLMUsage]:
    companies = [
        BriefCompany(company_id=c, name=companies_by_id[c].name if c in companies_by_id else c,
                     isic_division=isic_division(companies_by_id[c].isic_code) if c in companies_by_id else None)
        for c in candidate.candidate_sectors_companies
    ]
    unclassified = [c.company_id for c in companies if c.isic_division is None]
    pool = _evidence_pool(candidate, member_tags, mentions_by_id, company_ids_by_mention, unclassified)
    code_built = {
        "facts": _facts(candidate, member_tags, mentions_by_id, pool), "evidence": pool,
        "companies": companies, "sectors": _sectors(companies, pool),
    }
    try:
        draft, usage = await llm.complete_structured(
            system=_SYSTEM_PROMPT, prompt=_prompt(candidate, pool, companies, unclassified), output_model=_ContextBriefDraft,
        )
    except Exception:  # noqa: BLE001 - a failed wording call keeps the candidate and the code-built parts
        logger.exception("Context brief wording failed for candidate %s", candidate.theme_id)
        return ContextBrief(
            status="failed", error="brief wording failed", activities=BriefActivities(unclassified_company_ids=unclassified),
            **code_built,
        ), LLMUsage()
    kept, still_unclassified, dropped = _check_draft(draft, pool, unclassified)
    return ContextBrief(
        status="written", why_now=kept.why_now, early_evidence=kept.early_evidence,
        activities=BriefActivities(by_company=kept.by_company, groups=kept.groups, unclassified_company_ids=still_unclassified),
        dropped_statements=dropped, **code_built,
    ), usage
