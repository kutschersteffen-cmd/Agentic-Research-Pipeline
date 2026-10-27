from arp.config import Settings
from arp.research.indirect_exposure.core_sectors import (
    _CoreSectorSelection,
    classify_core_sectors,
    classify_theme_core_sectors,
)
from arp.research.indirect_exposure.factory import resolve_indirect_exposure_model
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition


def _model():
    return resolve_indirect_exposure_model(Settings(), use_sample=True)


async def test_supplied_core_codes_skip_the_llm_entirely(fake_llm):
    model = _model()
    activity = ActivityDefinition(
        name="EV manufacturing",
        in_scope_description="x",
        out_of_scope_description="y",
        core_isic_codes=["C27", "C29", "bogus-code"],
    )
    llm = fake_llm({})  # no scripted responses -- must not be called
    codes, usage = await classify_core_sectors(activity, model, llm)
    assert set(codes) == {"C27", "C29"}  # unknown code filtered out
    assert llm.calls == []
    assert usage.input_tokens == 0


async def test_llm_derived_core_codes_are_filtered_against_known_list(fake_llm):
    model = _model()
    activity = ActivityDefinition(name="EV manufacturing", in_scope_description="x", out_of_scope_description="y")
    draft = _CoreSectorSelection(isic_codes=["C27", "C29", "not-a-real-code"], rationale="battery + assembly")
    llm = fake_llm({_CoreSectorSelection.__name__: [draft]})

    codes, usage = await classify_core_sectors(activity, model, llm)
    assert set(codes) == {"C27", "C29"}
    assert llm.calls == [_CoreSectorSelection.__name__]


async def test_classify_theme_core_sectors_updates_every_activity(fake_llm):
    model = _model()
    theme = ThemeDefinition(
        name="Electrification",
        description="",
        activities=[
            ActivityDefinition(name="EV manufacturing", in_scope_description="x", out_of_scope_description="y"),
            ActivityDefinition(
                name="Grid infrastructure", in_scope_description="x", out_of_scope_description="y", core_isic_codes=["D"]
            ),
        ],
    )
    draft = _CoreSectorSelection(isic_codes=["C27"], rationale="battery/electrical equipment")
    llm = fake_llm({_CoreSectorSelection.__name__: [draft]})

    updated, usage = await classify_theme_core_sectors(theme, model, llm)
    assert updated.activities[0].core_isic_codes == ["C27"]
    assert updated.activities[1].core_isic_codes == ["D"]  # already supplied, no LLM call needed for this one
    assert llm.calls == [_CoreSectorSelection.__name__]  # only one call, for the activity missing core codes
