from __future__ import annotations

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient, LLMUsage
from arp.research.taxonomy_sources.activity_merge import merge_activity_sets
from arp.schemas.taxonomy import ActivityDuplicateCandidate, Taxonomy, TaxonomyComparison
from arp.schemas.thematic import ThemeDefinition

_COMPARE_SYSTEM_PROMPT = """\
You compare two thematic-investment taxonomies' activity sets and identify \
which activities are likely describing the same underlying business \
activity, even if worded or scoped slightly differently.

For every pair you believe are duplicates, return their activity_ids (one \
from each taxonomy) and a one-sentence similarity_note explaining why. Do \
not force a match when two activities are genuinely different, even if \
related -- only report pairs you're reasonably confident describe the \
same thing."""


class _DuplicatePairDraft(BaseModel):
    activity_a_id: str
    activity_b_id: str
    similarity_note: str


class _ComparisonDraft(BaseModel):
    likely_duplicates: list[_DuplicatePairDraft] = Field(default_factory=list)


def _format_activities(activities) -> str:
    return "\n".join(f"- [{a.activity_id}] {a.name}: {a.in_scope_description}" for a in activities)


async def compare_taxonomies(a: Taxonomy, b: Taxonomy, llm: LLMClient) -> tuple[TaxonomyComparison, LLMUsage]:
    """Diffs two taxonomies' activity sets. Duplicate detection is
    LLM-assisted (activity names/wording won't match exactly across
    different derivation methods); the returned pairs are validated
    against the taxonomies' actual activity_ids, same defensive pattern as
    core_sectors.py/company_mapper.py -- a hallucinated id is dropped, not
    trusted.
    """
    prompt = (
        f"Taxonomy A ({a.name} v{a.version}):\n{_format_activities(a.theme.activities)}\n\n"
        f"Taxonomy B ({b.name} v{b.version}):\n{_format_activities(b.theme.activities)}"
    )
    draft, usage = await llm.complete_structured(system=_COMPARE_SYSTEM_PROMPT, prompt=prompt, output_model=_ComparisonDraft)

    a_ids = {act.activity_id for act in a.theme.activities}
    b_ids = {act.activity_id for act in b.theme.activities}
    matched_a: set[str] = set()
    matched_b: set[str] = set()
    valid_pairs: list[ActivityDuplicateCandidate] = []
    for pair in draft.likely_duplicates:
        if pair.activity_a_id in a_ids and pair.activity_b_id in b_ids:
            valid_pairs.append(
                ActivityDuplicateCandidate(
                    activity_a_id=pair.activity_a_id, activity_b_id=pair.activity_b_id, similarity_note=pair.similarity_note
                )
            )
            matched_a.add(pair.activity_a_id)
            matched_b.add(pair.activity_b_id)

    comparison = TaxonomyComparison(
        unique_to_a=sorted(a_ids - matched_a),
        unique_to_b=sorted(b_ids - matched_b),
        likely_duplicates=valid_pairs,
    )
    return comparison, usage


async def merge_taxonomies(
    taxonomies: list[Taxonomy], name: str, description: str, llm: LLMClient
) -> tuple[ThemeDefinition, str, LLMUsage]:
    """Consolidates two or more saved taxonomies into one draft
    ThemeDefinition via the shared merge_activity_sets primitive. Returns
    a draft only -- saving it as a new taxonomy (method=MERGED) is a
    separate, explicit step the caller takes after the user reviews it.
    """
    activity_groups = [t.theme.activities for t in taxonomies]
    merged_activities, merge_notes, usage = await merge_activity_sets(name, description, activity_groups, llm)
    theme = ThemeDefinition(name=name, description=description, activities=merged_activities)
    sources = ", ".join(f"{t.name} v{t.version}" for t in taxonomies)
    notes = f"Merged from: {sources}. {merge_notes}"
    return theme, notes, usage
