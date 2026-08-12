from __future__ import annotations

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient, LLMUsage
from arp.research.indirect_exposure.leontief import LeontiefModel
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition

_SYSTEM_PROMPT = """\
You classify a thematic investment activity against a fixed list of ISIC \
Rev.4 industries from an input-output model, identifying which industries \
are its "core" value-chain sectors -- the industries whose output IS the \
activity, as opposed to industries merely economically linked to it.

Select only industries that are directly, primarily engaged in the \
activity as described. Do not select an industry just because it is a \
plausible supplier or customer of the activity -- that indirect linkage is \
computed separately, downstream of your classification, via the input- \
output model itself. If no listed industry is a good direct match, return \
an empty list rather than picking the closest-sounding one."""


class _CoreSectorSelection(BaseModel):
    isic_codes: list[str] = Field(default_factory=list)
    rationale: str


def _format_industry_list(model: LeontiefModel) -> str:
    return "\n".join(f"{code}: {model.labels.get(code, '')}" for code in model.codes)


async def classify_core_sectors(
    activity: ActivityDefinition, model: LeontiefModel, llm: LLMClient
) -> tuple[list[str], LLMUsage]:
    """Resolves an activity's core ISIC codes.

    If the activity already has `core_isic_codes` set (hand-supplied, the
    precise path), those are used directly with zero LLM cost. Otherwise a
    single classification call is made against the model's fixed, closed
    industry list -- one call per activity, not per company, since this is
    theme-level metadata that doesn't change across the company universe.
    """
    if activity.core_isic_codes:
        known = set(model.codes)
        return [c for c in activity.core_isic_codes if c in known], LLMUsage()

    prompt = (
        f"Activity: {activity.name}\n"
        f"In scope: {activity.in_scope_description}\n"
        f"Out of scope: {activity.out_of_scope_description}\n\n"
        f"Available ISIC Rev.4 industries:\n{_format_industry_list(model)}"
    )
    draft, usage = await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=_CoreSectorSelection)
    known = set(model.codes)
    valid_codes = [c for c in draft.isic_codes if c in known]
    return valid_codes, usage


async def classify_theme_core_sectors(
    theme: ThemeDefinition, model: LeontiefModel, llm: LLMClient
) -> tuple[ThemeDefinition, LLMUsage]:
    """Populates core_isic_codes on every activity in the theme that doesn't
    already have them. Intended to be run once per theme (e.g. via `arp
    theme classify-sectors`) before a run that enables the indirect-
    exposure tier, not repeated per company.
    """
    total_usage = LLMUsage()
    new_activities: list[ActivityDefinition] = []
    for activity in theme.activities:
        codes, usage = await classify_core_sectors(activity, model, llm)
        total_usage = LLMUsage(
            input_tokens=total_usage.input_tokens + usage.input_tokens,
            output_tokens=total_usage.output_tokens + usage.output_tokens,
        )
        new_activities.append(activity.model_copy(update={"core_isic_codes": codes}))
    return theme.model_copy(update={"activities": new_activities}), total_usage
