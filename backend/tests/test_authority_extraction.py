from arp.research.taxonomy_sources.authority_extraction import (
    _AuthorityActivityDraft,
    _AuthorityActivityDraftList,
    extract_activities_from_source,
)


async def test_grounded_quote_produces_activity_with_citation(fake_llm):
    text = "The taxonomy defines EV battery manufacturing as a core electrification activity."
    draft = _AuthorityActivityDraftList(
        activities=[
            _AuthorityActivityDraft(
                name="EV battery manufacturing", in_scope_description="x", out_of_scope_description="y",
                source_quote="EV battery manufacturing as a core electrification activity",
            )
        ]
    )
    llm = fake_llm({_AuthorityActivityDraftList.__name__: [draft]})

    activities, usage = await extract_activities_from_source("https://example.com/tax", text, llm)
    assert len(activities) == 1
    assert activities[0].source_citation is not None
    assert activities[0].source_citation.grounded is True
    assert activities[0].source_citation.location == "https://example.com/tax"
    assert usage.input_tokens > 0


async def test_hallucinated_quote_dropped_directly(fake_llm):
    text = "The taxonomy defines EV battery manufacturing as a core activity."
    draft = _AuthorityActivityDraftList(
        activities=[
            _AuthorityActivityDraft(
                name="Fabricated", in_scope_description="x", out_of_scope_description="y",
                source_quote="this text does not appear anywhere in the source document",
            )
        ]
    )
    llm = fake_llm({_AuthorityActivityDraftList.__name__: [draft]})

    activities, _usage = await extract_activities_from_source("https://example.com/tax", text, llm)
    assert activities == []


async def test_empty_source_text_skips_llm(fake_llm):
    llm = fake_llm({})
    activities, usage = await extract_activities_from_source("https://example.com/tax", "", llm)
    assert activities == []
    assert llm.calls == []
    assert usage.input_tokens == 0


async def test_mixed_grounded_and_ungrounded_keeps_only_grounded(fake_llm):
    text = "Grid modernization is in scope. Nothing here about hydrogen fuel cells."
    draft = _AuthorityActivityDraftList(
        activities=[
            _AuthorityActivityDraft(name="Grid modernization", in_scope_description="x", out_of_scope_description="y", source_quote="Grid modernization is in scope"),
            _AuthorityActivityDraft(name="Hydrogen fuel cells", in_scope_description="x", out_of_scope_description="y", source_quote="hydrogen fuel cell production reached record highs"),
        ]
    )
    llm = fake_llm({_AuthorityActivityDraftList.__name__: [draft]})

    activities, _usage = await extract_activities_from_source("https://example.com/tax", text, llm)
    assert len(activities) == 1
    assert activities[0].name == "Grid modernization"
