from __future__ import annotations

from arp.llm.base import LLMClient, LLMUsage
from arp.orchestration.cost_tracker import combine_usage
from arp.research.taxonomy_sources.activity_merge import merge_activity_sets
from arp.research.taxonomy_sources.authority_extraction import extract_activities_from_source
from arp.research.taxonomy_sources.fetch import fetch_source_text
from arp.schemas.thematic import ThemeDefinition

_MAX_CHARS_PER_SOURCE = 20_000


async def build_theme_from_authority_sources(
    theme_name: str,
    theme_description: str,
    source_urls: list[str],
    llm: LLMClient,
    user_agent: str,
) -> tuple[ThemeDefinition, str, LLMUsage]:
    """Fetches each user-selected authority source, extracts a grounded
    activity list from each independently (see authority_extraction.py),
    then -- if more than one source was selected -- consolidates them into
    one MECE set via the same merge primitive taxonomy comparison/merge
    uses. A source that fails to fetch, or yields no grounded activities,
    is skipped rather than failing the whole derivation.
    """
    per_source_activities: list[list] = []
    fetched_urls: list[str] = []
    empty_urls: list[str] = []
    unreachable_urls: list[str] = []
    total_usage = LLMUsage()

    for url in source_urls:
        text = await fetch_source_text(url, user_agent)
        if not text:
            unreachable_urls.append(url)
            continue
        activities, usage = await extract_activities_from_source(url, text[:_MAX_CHARS_PER_SOURCE], llm)
        total_usage = combine_usage(total_usage, usage)
        if not activities:
            empty_urls.append(url)
            continue
        fetched_urls.append(url)
        per_source_activities.append(activities)

    if not per_source_activities:
        raise ValueError(
            "No grounded activities could be extracted from the provided authority source URLs "
            f"(unreachable: {unreachable_urls or 'none'}; no groundable activities found: {empty_urls or 'none'})."
        )

    merged_activities, merge_notes, merge_usage = await merge_activity_sets(
        theme_name, theme_description, per_source_activities, llm
    )
    total_usage = combine_usage(total_usage, merge_usage)

    theme = ThemeDefinition(name=theme_name, description=theme_description, activities=merged_activities)

    notes = f"Grounded extraction from {len(fetched_urls)} authority source(s): {', '.join(fetched_urls)}."
    if len(per_source_activities) > 1:
        notes += f" {merge_notes}"
    if unreachable_urls:
        notes += f" Could not fetch: {', '.join(unreachable_urls)}."
    if empty_urls:
        notes += f" No groundable activities found in: {', '.join(empty_urls)}."
    return theme, notes, total_usage
