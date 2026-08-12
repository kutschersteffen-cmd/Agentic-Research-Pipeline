from arp.research.taxonomy_sources.activity_merge import _MergedActivityDraft, _MergedActivityDraftList, merge_activity_sets
from arp.schemas.thematic import ActivityDefinition


def _activity(name: str) -> ActivityDefinition:
    return ActivityDefinition(name=name, in_scope_description="x", out_of_scope_description="y")


async def test_single_group_short_circuits_without_llm(fake_llm):
    group = [_activity("EV manufacturing")]
    llm = fake_llm({})
    activities, notes, usage = await merge_activity_sets("Theme", "desc", [group], llm)
    assert activities == group
    assert "nothing to merge" in notes.lower()
    assert llm.calls == []
    assert usage.input_tokens == 0


async def test_empty_groups_short_circuit(fake_llm):
    llm = fake_llm({})
    activities, notes, usage = await merge_activity_sets("Theme", "desc", [[], []], llm)
    assert activities == []
    assert llm.calls == []


async def test_multi_group_merge_calls_llm(fake_llm):
    group_a = [_activity("Battery manufacturing")]
    group_b = [_activity("EV battery production"), _activity("Grid modernization")]

    draft = _MergedActivityDraftList(
        activities=[
            _MergedActivityDraft(name="Battery manufacturing", in_scope_description="x", out_of_scope_description="y"),
            _MergedActivityDraft(name="Grid modernization", in_scope_description="x", out_of_scope_description="y"),
        ],
        merge_notes="Combined the two battery-related activities; kept grid modernization separate.",
    )
    llm = fake_llm({_MergedActivityDraftList.__name__: [draft]})

    activities, notes, usage = await merge_activity_sets("Electrification", "desc", [group_a, group_b], llm)
    assert len(activities) == 2
    assert "Combined the two battery-related" in notes
    assert usage.input_tokens > 0
