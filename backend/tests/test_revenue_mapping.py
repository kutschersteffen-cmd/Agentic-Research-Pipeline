from arp.research.revenue_exposure.mapping import _LabelSelection, suggest_catalogue_mapping
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition


def _theme() -> ThemeDefinition:
    activity = ActivityDefinition(name="EV manufacturing", in_scope_description="x", out_of_scope_description="y")
    return ThemeDefinition(name="Electrification", description="", activities=[activity])


async def test_valid_label_is_kept(fake_llm):
    theme = _theme()
    draft = _LabelSelection(matched_labels=["EV Battery Systems"], rationale="Matches EV manufacturing directly.")
    llm = fake_llm({_LabelSelection.__name__: [draft, draft]})  # revenue + capex calls

    mappings, usage = await suggest_catalogue_mapping(theme, {"revenue": ["EV Battery Systems", "Legacy Parts"], "capex": ["EV Battery Systems"]}, llm)
    revenue_mapping = next(m for m in mappings if m.metric == "revenue")
    assert revenue_mapping.matched_labels == ["EV Battery Systems"]
    assert usage.input_tokens > 0


async def test_hallucinated_label_is_dropped(fake_llm):
    theme = _theme()
    draft = _LabelSelection(matched_labels=["Nonexistent Label"], rationale="bogus")
    llm = fake_llm({_LabelSelection.__name__: [draft]})

    mappings, _usage = await suggest_catalogue_mapping(theme, {"revenue": ["EV Battery Systems"]}, llm)
    assert mappings == []


async def test_empty_label_list_skips_llm_for_that_metric(fake_llm):
    theme = _theme()
    llm = fake_llm({})
    mappings, usage = await suggest_catalogue_mapping(theme, {"revenue": [], "capex": []}, llm)
    assert mappings == []
    assert usage.input_tokens == 0
    assert llm.calls == []
