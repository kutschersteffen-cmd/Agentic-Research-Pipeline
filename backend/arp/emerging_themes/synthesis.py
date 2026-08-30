from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel

from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.emerging_themes import (
    CandidateStatus,
    EmergingThemeCandidate,
    ExtractedTag,
    MentionCitation,
    RawMention,
    TopicCluster,
)

_SYSTEM_PROMPT = """\
You are naming a candidate investment theme from a cluster of \
independently corroborated business/market signals. A purely statistical \
detector has already judged these claims to be one coherent, novel topic \
-- your job is to name it and explain why it matters, not to decide \
whether it is real.

Draft:
- theme_name: a short, market-facing name for this theme (e.g. \
"Solid-state EV battery commercialization"), grounded in what the claims \
actually describe -- never a vague category like "batteries".
- description: 1-2 sentences describing what this theme is.
- economic_rationale: why this pattern would plausibly move markets or \
matter to investors -- NOT just that mention volume is rising. Name a \
concrete mechanism: a new revenue pool, a cost-structure shift, a \
regulatory tailwind/headwind, a competitive repositioning. This field is \
required and must state a specific mechanism, not restate the \
description.
- rationale: a short narrative summary of the evidence, referencing the \
specific claims given.

Ground every statement in the material given -- do not add outside \
knowledge not evidenced by the supplied claims."""


class _CandidateDraft(BaseModel):
    theme_name: str
    description: str
    economic_rationale: str
    rationale: str


async def _draft_narrative(cluster: TopicCluster, member_tags: list[ExtractedTag], llm: LLMClient) -> tuple[_CandidateDraft, LLMUsage]:
    listing = "\n\n".join(f'- {t.claim} (quote: "{t.quote}")' for t in member_tags[:20])
    prompt = (
        f"Cluster top terms: {cluster.representative_label}\n"
        f"Companies involved: {', '.join(cluster.company_ids) or 'none resolved'}\n\n"
        f"Claims:\n{listing}"
    )
    return await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=_CandidateDraft)


def independent_source_count(member_tags: list[ExtractedTag], mentions_by_id: dict[str, RawMention]) -> int:
    """How many distinct primary sources back this cluster -- the source
    plan's 'independent-source minimum' safeguard. Computed over every
    grounded member tag, not just the ones that end up in the displayed
    citation list, so capping citations for readability never quietly
    weakens this check."""
    urls = {
        mentions_by_id[t.mention_id].url
        for t in member_tags
        if t.grounded and t.mention_id in mentions_by_id
    }
    return len(urls)


def _select_citations(member_tags: list[ExtractedTag], mentions_by_id: dict[str, RawMention], max_citations: int = 8) -> list[MentionCitation]:
    seen_urls: set[str] = set()
    citations: list[MentionCitation] = []
    for tag in member_tags:
        if not tag.grounded:
            continue
        mention = mentions_by_id.get(tag.mention_id)
        if mention is None or mention.url in seen_urls:
            continue
        seen_urls.add(mention.url)
        citations.append(MentionCitation(mention_id=mention.mention_id, source_type=mention.source_type, url=mention.url, quote=tag.quote, grounded=True))
        if len(citations) >= max_citations:
            break
    return citations


async def build_candidate(
    cluster: TopicCluster,
    member_tags: list[ExtractedTag],
    mentions_by_id: dict[str, RawMention],
    llm: LLMClient,
    run_id: str,
    *,
    min_independent_sources: int = 2,
) -> tuple[EmergingThemeCandidate | None, LLMUsage]:
    """The Synthesize layer: turns one surviving (BIRTH-classified,
    stability-gated) cluster into an `EmergingThemeCandidate`, or returns
    None if it fails the independent-source-minimum check before ever
    reaching the LLM -- a simple, cheap filter that doesn't need the
    Phase 2 verification-agent machinery to be worth enforcing now.
    """
    source_count = independent_source_count(member_tags, mentions_by_id)
    if source_count < min_independent_sources:
        return None, LLMUsage()

    draft, usage = await _draft_narrative(cluster, member_tags, llm)
    citations = _select_citations(member_tags, mentions_by_id)

    candidate = EmergingThemeCandidate(
        theme_name=draft.theme_name,
        description=draft.description,
        first_detected_date=datetime.now(timezone.utc).date().isoformat(),
        signal_velocity=float(cluster.mention_count),
        corroborating_sources=citations,
        candidate_sectors_companies=cluster.company_ids,
        rationale=draft.rationale,
        economic_rationale=draft.economic_rationale,
        confidence_score=cluster.stability_score,
        status=CandidateStatus.CANDIDATE,
        cluster_id=cluster.cluster_id,
        run_id=run_id,
    )
    return candidate, usage
