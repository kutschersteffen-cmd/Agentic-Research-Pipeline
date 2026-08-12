from arp.research.taxonomy_sources.activity_merge import _MergedActivityDraft, _MergedActivityDraftList
from arp.research.taxonomy_sources.compare import _ComparisonDraft, _DuplicatePairDraft, compare_taxonomies, merge_taxonomies
from arp.schemas.taxonomy import DerivationMethod, Taxonomy
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition


def _taxonomy(name: str, activity_names: list[str]) -> Taxonomy:
    theme = ThemeDefinition(
        name=name, description="", activities=[ActivityDefinition(name=n, in_scope_description="x", out_of_scope_description="y") for n in activity_names]
    )
    return Taxonomy(name=name, theme=theme, derivation_method=DerivationMethod.LLM_DRAFT)


async def test_compare_taxonomies_validates_ids_against_real_activities(fake_llm):
    tax_a = _taxonomy("A", ["EV manufacturing", "Grid modernization"])
    tax_b = _taxonomy("B", ["Electric vehicle production", "Battery recycling"])

    real_pair = _DuplicatePairDraft(
        activity_a_id=tax_a.theme.activities[0].activity_id,
        activity_b_id=tax_b.theme.activities[0].activity_id,
        similarity_note="Both describe EV manufacturing.",
    )
    hallucinated_pair = _DuplicatePairDraft(activity_a_id="act_doesnotexist", activity_b_id="act_alsofake", similarity_note="bogus")
    draft = _ComparisonDraft(likely_duplicates=[real_pair, hallucinated_pair])
    llm = fake_llm({_ComparisonDraft.__name__: [draft]})

    comparison, usage = await compare_taxonomies(tax_a, tax_b, llm)
    assert len(comparison.likely_duplicates) == 1  # hallucinated pair filtered out
    assert comparison.likely_duplicates[0].activity_a_id == tax_a.theme.activities[0].activity_id
    assert comparison.unique_to_a == [tax_a.theme.activities[1].activity_id]
    assert comparison.unique_to_b == [tax_b.theme.activities[1].activity_id]
    assert usage.input_tokens > 0


async def test_compare_no_duplicates_everything_unique(fake_llm):
    tax_a = _taxonomy("A", ["EV manufacturing"])
    tax_b = _taxonomy("B", ["Grid modernization"])
    draft = _ComparisonDraft(likely_duplicates=[])
    llm = fake_llm({_ComparisonDraft.__name__: [draft]})

    comparison, _usage = await compare_taxonomies(tax_a, tax_b, llm)
    assert comparison.unique_to_a == [tax_a.theme.activities[0].activity_id]
    assert comparison.unique_to_b == [tax_b.theme.activities[0].activity_id]
    assert comparison.likely_duplicates == []


async def test_merge_taxonomies_produces_draft_not_saved(fake_llm):
    tax_a = _taxonomy("A", ["EV manufacturing"])
    tax_b = _taxonomy("B", ["Grid modernization"])
    draft = _MergedActivityDraftList(
        activities=[
            _MergedActivityDraft(name="EV manufacturing", in_scope_description="x", out_of_scope_description="y"),
            _MergedActivityDraft(name="Grid modernization", in_scope_description="x", out_of_scope_description="y"),
        ],
        merge_notes="No overlap; kept both.",
    )
    llm = fake_llm({_MergedActivityDraftList.__name__: [draft]})

    theme, notes, usage = await merge_taxonomies([tax_a, tax_b], "Merged Electrification", "desc", llm)
    assert isinstance(theme, ThemeDefinition)
    assert len(theme.activities) == 2
    assert "A v1" in notes and "B v1" in notes
    assert "No overlap" in notes
    assert usage.input_tokens > 0
