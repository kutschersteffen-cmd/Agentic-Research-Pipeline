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


# --- Industry-anchored derivation: grounds the draft against a real,
# closed industry classification (e.g. the ISIC list from a loaded
# input-output model) instead of letting the model invent categories
# freely. Populates core_isic_codes directly, since the same reference
# list is what `arp/research/indirect_exposure/core_sectors.py` would
# otherwise classify against as a separate step. ---

_ANCHORED_SYSTEM_PROMPT = """\
You are a thematic-investment taxonomist. Given a macro investment theme \
AND a fixed reference list of real industry classifications, decompose the \
theme into a set of concrete, mutually-exclusive-and-collectively- \
exhaustive (MECE) business activities that companies can be screened \
against -- grounded in that reference list wherever a clean match exists, \
rather than invented from scratch.

For each activity, write the in-scope and out-of-scope descriptions in \
plain, checkable language, in the style used by systematic thematic index \
providers, and give a short seed keyword/bigram list for evidence \
retrieval. Additionally, select which of the reference industries (by \
code) are this activity's core sectors -- industries whose output IS the \
activity, not merely a plausible supplier or customer of it. If no \
reference industry is a good direct match for an activity, leave its \
core_isic_codes empty rather than forcing the closest-sounding one; not \
every real activity in a theme needs to map onto this particular \
reference list.

Produce between 4 and 10 activities. Avoid overlap between activities."""


class _AnchoredActivityDraft(BaseModel):
    name: str
    in_scope_description: str
    out_of_scope_description: str
    seed_keywords: list[str] = Field(default_factory=list)
    core_isic_codes: list[str] = Field(default_factory=list)


class _AnchoredActivityDraftList(BaseModel):
    activities: list[_AnchoredActivityDraft]


def _format_anchor_industries(anchor_industries: list[tuple[str, str]]) -> str:
    return "\n".join(f"{code}: {label}" for code, label in anchor_industries)


async def generate_activities_industry_anchored(
    theme_name: str,
    theme_description: str,
    anchor_industries: list[tuple[str, str]],
    llm: LLMClient,
) -> tuple[list[ActivityDefinition], LLMUsage]:
    prompt = (
        f"Macro theme: {theme_name}\n"
        f"Theme description: {theme_description}\n\n"
        f"Reference industry classification:\n{_format_anchor_industries(anchor_industries)}\n\n"
        "Decompose this theme into MECE business activities per your instructions."
    )
    draft, usage = await llm.complete_structured(
        system=_ANCHORED_SYSTEM_PROMPT, prompt=prompt, output_model=_AnchoredActivityDraftList
    )
    known_codes = {code for code, _ in anchor_industries}
    activities = [
        ActivityDefinition(
            name=a.name,
            in_scope_description=a.in_scope_description,
            out_of_scope_description=a.out_of_scope_description,
            seed_keywords=a.seed_keywords,
            core_isic_codes=[c for c in a.core_isic_codes if c in known_codes],
        )
        for a in draft.activities
    ]
    return activities, usage


async def build_theme_industry_anchored(
    name: str, description: str, anchor_industries: list[tuple[str, str]], llm: LLMClient
) -> tuple[ThemeDefinition, LLMUsage]:
    activities, usage = await generate_activities_industry_anchored(name, description, anchor_industries, llm)
    return ThemeDefinition(name=name, description=description, activities=activities), usage
