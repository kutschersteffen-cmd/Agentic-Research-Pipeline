from __future__ import annotations

from arp.llm.base import LLMClient, LLMUsage
from arp.research.activity_generator import build_theme
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
    """Fetches each user-selected authority source and grounds the activity
    draft in their actual text (see activity_generator.generate_activities'
    extra_context). A source that fails to fetch is skipped, not fatal --
    one dead link shouldn't block a derivation that has other sources.
    """
    fetched: list[tuple[str, str]] = []
    for url in source_urls:
        text = await fetch_source_text(url, user_agent)
        if text:
            fetched.append((url, text[:_MAX_CHARS_PER_SOURCE]))

    if not fetched:
        raise ValueError("None of the provided authority source URLs could be fetched.")

    extra_context = "\n\n".join(f"[Source: {url}]\n{text}" for url, text in fetched)
    theme, usage = await build_theme(theme_name, theme_description, llm, extra_context=extra_context)

    fetched_urls = [url for url, _ in fetched]
    skipped = [u for u in source_urls if u not in fetched_urls]
    notes = f"Grounded against {len(fetched)} authority source(s): {', '.join(fetched_urls)}."
    if skipped:
        notes += f" Could not fetch: {', '.join(skipped)}."
    return theme, notes, usage
