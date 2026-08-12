from __future__ import annotations

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.thematic import ActivityDefinition

_SYSTEM_PROMPT = """\
You are a thematic-investment taxonomist consolidating several activity \
lists (drawn from different sources, or different saved taxonomies) about \
the same macro theme into one MECE set.

Merge activities that describe the same underlying business activity even \
if worded differently, keeping the clearer or more precise of the two \
descriptions (or synthesizing a better one). Keep activities distinct \
when they describe genuinely different things, even if related. Every \
activity in your output must map back to at least one activity in the \
input -- do not introduce a new activity that wasn't present in any input \
list. Explain your consolidation decisions in merge_notes: what you \
combined, what you kept separate and why, and anything you dropped as a \
near-exact duplicate."""


class _MergedActivityDraft(BaseModel):
    name: str
    in_scope_description: str
    out_of_scope_description: str
    seed_keywords: list[str] = Field(default_factory=list)


class _MergedActivityDraftList(BaseModel):
    activities: list[_MergedActivityDraft]
    merge_notes: str


def _format_activity_groups(activity_groups: list[list[ActivityDefinition]]) -> str:
    blocks = []
    for i, group in enumerate(activity_groups):
        group_label = f"Group {i + 1}"
        activity_lines = "\n".join(
            f"- {a.name}: {a.in_scope_description} (out of scope: {a.out_of_scope_description})" for a in group
        )
        blocks.append(f"{group_label}:\n{activity_lines}" if activity_lines else f"{group_label}: (no activities)")
    return "\n\n".join(blocks)


async def merge_activity_sets(
    theme_name: str,
    theme_description: str,
    activity_groups: list[list[ActivityDefinition]],
    llm: LLMClient,
) -> tuple[list[ActivityDefinition], str, LLMUsage]:
    """Consolidates several ActivityDefinition lists into one MECE set.

    Shared by two callers: multi-source authority extraction (each
    selected source produces its own activity list) and taxonomy merge
    (each taxonomy being merged contributes its activity list). Neither
    caller saves the result directly -- it's handed back as an editable
    draft, the same way every other derivation method's output is.
    """
    non_empty_groups = [g for g in activity_groups if g]
    if len(non_empty_groups) <= 1:
        # Nothing to consolidate -- return the one group (or empty) as-is,
        # with source_citation/core_isic_codes preserved since there was no
        # LLM rewrite to potentially drop them.
        return (non_empty_groups[0] if non_empty_groups else []), "Only one non-empty source; nothing to merge.", LLMUsage()

    prompt = (
        f"Macro theme: {theme_name}\nDescription: {theme_description}\n\n"
        f"Activity lists to consolidate:\n{_format_activity_groups(non_empty_groups)}"
    )
    draft, usage = await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=_MergedActivityDraftList)
    activities = [
        ActivityDefinition(
            name=a.name, in_scope_description=a.in_scope_description, out_of_scope_description=a.out_of_scope_description,
            seed_keywords=a.seed_keywords,
        )
        for a in draft.activities
    ]
    return activities, draft.merge_notes, usage
