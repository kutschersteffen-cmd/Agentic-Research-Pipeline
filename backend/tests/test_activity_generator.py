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
    assert theme.activities[0].core_sectors == []  # freeform draft never populates this


async def test_industry_anchored_filters_unknown_codes(fake_llm):
    draft_list = _AnchoredActivityDraftList(
        activities=[
            _AnchoredActivityDraft(
                name="EV manufacturing",
                in_scope_description="Makes BEVs",
                out_of_scope_description="ICE only",
                seed_keywords=["electric vehicle"],
                core_sectors=["Manufacture of electrical machinery and apparatus n.e.c.", "Manufacture of motor vehicles, trailers and semi-trailers", "not-a-real-code"],
            )
        ]
    )
    llm = fake_llm({_AnchoredActivityDraftList.__name__: [draft_list]})
    anchors = ["Copper production", "Manufacture of electrical machinery and apparatus n.e.c.", "Manufacture of motor vehicles, trailers and semi-trailers"]

    activities, _usage = await generate_activities_industry_anchored("Electrification", "desc", anchors, llm)
    assert len(activities) == 1
    assert set(activities[0].core_sectors) == {"Manufacture of electrical machinery and apparatus n.e.c.", "Manufacture of motor vehicles, trailers and semi-trailers"}


async def test_industry_anchored_allows_empty_core_codes(fake_llm):
    """An activity with no clean match to the reference list should keep
    core_sectors empty rather than have a bad match forced in."""
    draft_list = _AnchoredActivityDraftList(
        activities=[
            _AnchoredActivityDraft(
                name="Policy advocacy",
                in_scope_description="Lobbying for EV incentives",
                out_of_scope_description="General corporate lobbying",
                seed_keywords=["policy"],
                core_sectors=[],
            )
        ]
    )
    llm = fake_llm({_AnchoredActivityDraftList.__name__: [draft_list]})
    anchors = ["Manufacture of electrical machinery and apparatus n.e.c."]

    activities, _usage = await generate_activities_industry_anchored("Electrification", "desc", anchors, llm)
    assert activities[0].core_sectors == []


async def test_anchored_drops_unlisted(fake_llm):  # AC-37
    from arp.config import Settings
    from arp.research.indirect_exposure.factory import resolve_indirect_exposure_model

    model = resolve_indirect_exposure_model(Settings(), use_sample=True)
    draft_list = _AnchoredActivityDraftList(activities=[_AnchoredActivityDraft(
        name="Copper", in_scope_description="x", out_of_scope_description="y", core_sectors=["Copper production", "Made-up sector"],
    )])
    llm = fake_llm({_AnchoredActivityDraftList.__name__: [draft_list]})
    activities, _ = await generate_activities_industry_anchored("t", "d", model.industry_reference_list(), llm)
    assert activities[0].core_sectors == ["Copper production"]
