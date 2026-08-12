from __future__ import annotations

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition

_SYSTEM_PROMPT = """\
You are a thematic-investment taxonomist. Given a macro investment theme, \
decompose it into a set of concrete, mutually-exclusive-and-collectively-\
exhaustive (MECE) business activities that companies can be screened against.

For each activity, write the in-scope and out-of-scope descriptions in \
plain, checkable language, in the style used by systematic thematic index \
providers: describe exactly what a business must be doing to count, and \
explicitly call out adjacent activities that must NOT count, so scope \
creep and false positives are avoidable later. Also give a short seed \
keyword/bigram list for each activity to drive initial evidence retrieval \
from company disclosures (10-Ks, sustainability reports, earnings calls).

Produce between 4 and 10 activities. Avoid overlap between activities."""


class _ActivityDraft(BaseModel):
    name: str
    in_scope_description: str
    out_of_scope_description: str
    seed_keywords: list[str] = Field(default_factory=list)


class _ActivityDraftList(BaseModel):
    activities: list[_ActivityDraft]


async def generate_activities(
    theme_name: str, theme_description: str, llm: LLMClient
) -> tuple[list[ActivityDefinition], LLMUsage]:
    prompt = (
        f"Macro theme: {theme_name}\n"
        f"Theme description: {theme_description}\n\n"
        "Decompose this theme into MECE business activities per your instructions."
    )
    draft, usage = await llm.complete_structured(
        system=_SYSTEM_PROMPT, prompt=prompt, output_model=_ActivityDraftList
    )
    activities = [
        ActivityDefinition(
            name=a.name,
            in_scope_description=a.in_scope_description,
            out_of_scope_description=a.out_of_scope_description,
            seed_keywords=a.seed_keywords,
        )
        for a in draft.activities
    ]
    return activities, usage


async def build_theme(name: str, description: str, llm: LLMClient) -> tuple[ThemeDefinition, LLMUsage]:
    activities, usage = await generate_activities(name, description, llm)
    return ThemeDefinition(name=name, description=description, activities=activities), usage
