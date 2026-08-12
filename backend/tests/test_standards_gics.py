from arp.research.standards_mapping.gics import GicsReferenceEntry, _GicsSelection, _GicsSelectionList, classify_gics
from arp.schemas.thematic import ActivityDefinition


def _activity() -> ActivityDefinition:
    return ActivityDefinition(
        name="EV manufacturing",
        in_scope_description="Design and assembly of battery-electric passenger vehicles.",
        out_of_scope_description="Traditional ICE vehicle manufacturing.",
    )


def _reference() -> list[GicsReferenceEntry]:
    return [
        GicsReferenceEntry(code="25", label="Consumer Discretionary", level="sector"),
        GicsReferenceEntry(code="20", label="Industrials", level="sector"),
    ]


async def test_valid_code_is_kept_with_rationale(fake_llm):
    draft = _GicsSelectionList(matches=[_GicsSelection(code="25", rationale="EV manufacturing is a consumer discretionary automobile activity.")])
    llm = fake_llm({_GicsSelectionList.__name__: [draft]})

    matches, usage = await classify_gics(_activity(), _reference(), llm)
    assert len(matches) == 1
    assert matches[0].code == "25"
    assert matches[0].label == "Consumer Discretionary"
    assert "consumer discretionary" in matches[0].rationale.lower()
    assert usage.input_tokens > 0


async def test_hallucinated_code_is_dropped(fake_llm):
    draft = _GicsSelectionList(matches=[_GicsSelection(code="99", rationale="bogus")])
    llm = fake_llm({_GicsSelectionList.__name__: [draft]})

    matches, _usage = await classify_gics(_activity(), _reference(), llm)
    assert matches == []


async def test_empty_reference_list_skips_llm(fake_llm):
    llm = fake_llm({})
    matches, usage = await classify_gics(_activity(), [], llm)
    assert matches == []
    assert usage.input_tokens == 0
    assert llm.calls == []
