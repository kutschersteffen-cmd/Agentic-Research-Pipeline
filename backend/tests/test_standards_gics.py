from collections import Counter
from pathlib import Path

from arp.research.standards_mapping.gics import GicsReferenceEntry, _GicsSelection, _GicsSelectionList, classify_gics, load_gics_reference
from arp.schemas.thematic import ActivityDefinition

_SAMPLE_PATH = Path(__file__).parent.parent / "arp/research/standards_mapping/sample_data/gics_reference_sample.csv"


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


def test_bundled_sample_covers_all_four_gics_levels_with_no_duplicate_codes():
    """Regression guard on the bundled (unverified, LLM-reconstructed --
    see sample_data/README.md) full GICS hierarchy: right shape, no
    accidental duplicate/colliding codes across levels."""
    entries = load_gics_reference(_SAMPLE_PATH)
    counts = Counter(e.level for e in entries)
    assert counts["sector"] == 11
    assert counts["industry_group"] == 25
    assert counts["industry"] > 60
    assert counts["sub_industry"] > 150
    codes = [e.code for e in entries]
    assert len(codes) == len(set(codes))
