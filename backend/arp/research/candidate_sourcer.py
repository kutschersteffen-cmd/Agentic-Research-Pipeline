from __future__ import annotations

from arp.schemas.common import DocumentChunk
from arp.schemas.thematic import ActivityDefinition


def prefilter_chunks_for_activity(
    chunks: list[DocumentChunk], activity: ActivityDefinition, min_hits: int = 1
) -> list[DocumentChunk]:
    """Cheap keyword-in-context prefilter (Sautner et al.-style) applied
    before any LLM call.

    At 4000-company scale, running the full Advocate/Opposing/Adjudicator
    LLM pipeline against every document chunk for every activity is neither
    affordable nor necessary: most chunks have zero relevance to a given
    activity. This filter narrows the evidence set down to chunks that
    actually mention the activity's seed keywords, which both controls
    cost and keeps the LLM's context focused (higher precision) rather
    than diluted across an entire filing.
    """
    if not activity.seed_keywords:
        return chunks
    return [c for c in chunks if len(c.keyword_hits) >= min_hits]


def company_has_candidate_evidence(chunks: list[DocumentChunk], activity: ActivityDefinition) -> bool:
    return len(prefilter_chunks_for_activity(chunks, activity)) > 0
