from arp.research.activity_generator import (
    _ActivityDraft,
    _ActivityDraftList,
    _AnchoredActivityDraft,
    _AnchoredActivityDraftList,
    build_theme,
    generate_activities_industry_anchored,
)


async def test_build_theme_freeform(fake_llm):
    draft_list = _ActivityDraftList(
        activities=[
            _ActivityDraft(
                name="EV manufacturing", in_scope_description="Makes BEVs", out_of_scope_description="ICE only",
                seed_keywords=["electric vehicle"],
            )
        ]
    )
    llm = fake_llm({_ActivityDraftList.__name__: [draft_list]})
    theme, _usage = await build_theme("Electrification", "desc", llm)
    assert theme.name == "Electrification"
    assert len(theme.activities) == 1
    assert theme.activities[0].core_isic_codes == []  # freeform draft never populates this


async def test_industry_anchored_filters_unknown_codes(fake_llm):
    draft_list = _AnchoredActivityDraftList(
        activities=[
            _AnchoredActivityDraft(
                name="EV manufacturing",
                in_scope_description="Makes BEVs",
                out_of_scope_description="ICE only",
                seed_keywords=["electric vehicle"],
                core_isic_codes=["27", "29", "not-a-real-code"],
            )
        ]
    )
    llm = fake_llm({_AnchoredActivityDraftList.__name__: [draft_list]})
    anchors = [("07", "Mining of metal ores"), ("27", "Manufacture of electrical equipment"), ("29", "Manufacture of motor vehicles")]

    activities, _usage = await generate_activities_industry_anchored("Electrification", "desc", anchors, llm)
    assert len(activities) == 1
    assert set(activities[0].core_isic_codes) == {"27", "29"}


async def test_industry_anchored_allows_empty_core_codes(fake_llm):
    """An activity with no clean match to the reference list should keep
    core_isic_codes empty rather than have a bad match forced in."""
    draft_list = _AnchoredActivityDraftList(
        activities=[
            _AnchoredActivityDraft(
                name="Policy advocacy",
                in_scope_description="Lobbying for EV incentives",
                out_of_scope_description="General corporate lobbying",
                seed_keywords=["policy"],
                core_isic_codes=[],
            )
        ]
    )
    llm = fake_llm({_AnchoredActivityDraftList.__name__: [draft_list]})
    anchors = [("27", "Manufacture of electrical equipment")]

    activities, _usage = await generate_activities_industry_anchored("Electrification", "desc", anchors, llm)
    assert activities[0].core_isic_codes == []
