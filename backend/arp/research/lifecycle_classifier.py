from __future__ import annotations

from pydantic import BaseModel

from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.thematic import ActivityDefinition, LifecycleStage, ThemeDefinition

_SYSTEM_PROMPT = """\
You classify a thematic-investment business activity by where it sits on \
the technology/commercialization curve, choosing exactly one stage:

- ideation: pre-commercial research; no company generates meaningful \
revenue from this activity yet (e.g. an emerging technology still in lab \
or pilot stage).
- innovation: early commercialization; a handful of companies have started \
generating revenue, but the activity is not yet a mainstream, widely \
reported business line.
- commercialization: an established, widely reported business line for \
many companies, with meaningful and growing revenue, but not yet mature/ \
saturated.
- mature: a long-established, saturated business line where revenue-\
percentage disclosure is the norm and growth has stabilized.

This choice determines which exposure-scoring method is used downstream: \
ideation/innovation-stage activities get scored via R&D-spend intensity \
and news-mention momentum (revenue-percentage data barely exists yet); \
commercialization/mature activities get scored via disclosed revenue \
percentage. Judge the ACTIVITY as generally practiced across the economy \
today, not any single company's position in it."""


class _LifecycleClassification(BaseModel):
    lifecycle_stage: LifecycleStage
    rationale: str


async def classify_lifecycle_stage(activity: ActivityDefinition, llm: LLMClient) -> tuple[LifecycleStage, LLMUsage]:
    """Resolves an activity's lifecycle_stage.

    If already set (hand-supplied, the precise path -- e.g. a domain expert
    curating the taxonomy), returned directly with zero LLM cost. Otherwise
    a single classification call is made -- one call per activity, not per
    company, since this is theme-level metadata that doesn't change across
    the company universe (the same "classify once, reuse everywhere"
    pattern as classify_core_sectors).
    """
    if activity.lifecycle_stage is not None:
        return activity.lifecycle_stage, LLMUsage()

    prompt = (
        f"Activity: {activity.name}\n"
        f"In scope: {activity.in_scope_description}\n"
        f"Out of scope: {activity.out_of_scope_description}"
    )
    draft, usage = await llm.complete_structured(system=_SYSTEM_PROMPT, prompt=prompt, output_model=_LifecycleClassification)
    return draft.lifecycle_stage, usage


async def classify_theme_lifecycle_stages(theme: ThemeDefinition, llm: LLMClient) -> tuple[ThemeDefinition, LLMUsage]:
    """Populates lifecycle_stage on every activity in the theme that doesn't
    already have one. Intended to be run once per theme (e.g. via `arp
    theme classify-lifecycle`) before a run that enables Method C
    (--enable-rd-exposure), which only does anything for ideation/
    innovation-stage activities.
    """
    total_usage = LLMUsage()
    new_activities: list[ActivityDefinition] = []
    for activity in theme.activities:
        stage, usage = await classify_lifecycle_stage(activity, llm)
        total_usage = LLMUsage(
            input_tokens=total_usage.input_tokens + usage.input_tokens,
            output_tokens=total_usage.output_tokens + usage.output_tokens,
        )
        new_activities.append(activity.model_copy(update={"lifecycle_stage": stage}))
    return theme.model_copy(update={"activities": new_activities}), total_usage
