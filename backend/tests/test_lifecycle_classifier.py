from arp.research.lifecycle_classifier import _LifecycleClassification, classify_lifecycle_stage, classify_theme_lifecycle_stages
from arp.schemas.thematic import ActivityDefinition, LifecycleStage, ThemeDefinition


async def test_supplied_lifecycle_stage_skips_the_llm_entirely(fake_llm):
    activity = ActivityDefinition(
        name="EV manufacturing", in_scope_description="x", out_of_scope_description="y", lifecycle_stage=LifecycleStage.MATURE
    )
    llm = fake_llm({})  # no scripted responses -- must not be called
    stage, usage = await classify_lifecycle_stage(activity, llm)
    assert stage == LifecycleStage.MATURE
    assert llm.calls == []
    assert usage.input_tokens == 0


async def test_llm_classifies_unset_lifecycle_stage(fake_llm):
    activity = ActivityDefinition(name="Solid-state batteries", in_scope_description="x", out_of_scope_description="y")
    draft = _LifecycleClassification(lifecycle_stage=LifecycleStage.IDEATION, rationale="Still pre-commercial.")
    llm = fake_llm({_LifecycleClassification.__name__: [draft]})

    stage, usage = await classify_lifecycle_stage(activity, llm)
    assert stage == LifecycleStage.IDEATION
    assert llm.calls == [_LifecycleClassification.__name__]


async def test_classify_theme_lifecycle_stages_updates_every_activity(fake_llm):
    theme = ThemeDefinition(
        name="Electrification", description="",
        activities=[
            ActivityDefinition(name="EV manufacturing", in_scope_description="x", out_of_scope_description="y"),
            ActivityDefinition(
                name="Grid infrastructure", in_scope_description="x", out_of_scope_description="y",
                lifecycle_stage=LifecycleStage.MATURE,
            ),
        ],
    )
    draft = _LifecycleClassification(lifecycle_stage=LifecycleStage.COMMERCIALIZATION, rationale="Widely adopted now.")
    llm = fake_llm({_LifecycleClassification.__name__: [draft]})

    updated, usage = await classify_theme_lifecycle_stages(theme, llm)
    assert updated.activities[0].lifecycle_stage == LifecycleStage.COMMERCIALIZATION
    assert updated.activities[1].lifecycle_stage == LifecycleStage.MATURE  # already supplied, no LLM call needed
    assert llm.calls == [_LifecycleClassification.__name__]  # only one call, for the activity missing a stage
