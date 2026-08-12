import pytest

from arp.research.taxonomy_sources import authority as authority_module
from arp.research.taxonomy_sources.authority_extraction import _AuthorityActivityDraft, _AuthorityActivityDraftList


async def test_build_theme_from_authority_sources_grounds_on_fetched_text(fake_llm, monkeypatch):
    async def fake_fetch(url, user_agent, timeout=20.0):
        if url == "https://iea.org/taxonomy":
            return "The IEA defines electrification as the direct use of electricity in end-use sectors."
        return None  # this one fails to fetch

    monkeypatch.setattr(authority_module, "fetch_source_text", fake_fetch)

    draft = _AuthorityActivityDraftList(
        activities=[
            _AuthorityActivityDraft(
                name="Direct electrification",
                in_scope_description="x",
                out_of_scope_description="y",
                seed_keywords=["electrification"],
                source_quote="direct use of electricity in end-use sectors",
            )
        ]
    )
    llm = fake_llm({_AuthorityActivityDraftList.__name__: [draft]})

    theme, notes, usage = await authority_module.build_theme_from_authority_sources(
        "Electrification", "desc", ["https://iea.org/taxonomy", "https://dead-link.example.com"], llm, "test-agent"
    )
    assert theme.name == "Electrification"
    assert len(theme.activities) == 1
    assert theme.activities[0].source_citation is not None
    assert theme.activities[0].source_citation.grounded is True
    assert "iea.org/taxonomy" in notes
    assert "dead-link.example.com" in notes  # noted as unfetchable, not silently dropped
    assert usage.input_tokens > 0


async def test_ungrounded_quote_is_dropped_not_trusted(fake_llm, monkeypatch):
    async def fake_fetch(url, user_agent, timeout=20.0):
        return "The IEA defines electrification as the direct use of electricity in end-use sectors."

    monkeypatch.setattr(authority_module, "fetch_source_text", fake_fetch)

    # this quote does not actually appear in the fetched text
    draft = _AuthorityActivityDraftList(
        activities=[
            _AuthorityActivityDraft(
                name="Fabricated activity",
                in_scope_description="x",
                out_of_scope_description="y",
                source_quote="this exact phrase is nowhere in the source",
            )
        ]
    )
    llm = fake_llm({_AuthorityActivityDraftList.__name__: [draft]})

    with pytest.raises(ValueError):
        await authority_module.build_theme_from_authority_sources("Electrification", "desc", ["https://iea.org/taxonomy"], llm, "test-agent")


async def test_build_theme_from_authority_sources_all_fail_raises(fake_llm, monkeypatch):
    async def fake_fetch(url, user_agent, timeout=20.0):
        return None

    monkeypatch.setattr(authority_module, "fetch_source_text", fake_fetch)
    llm = fake_llm({})

    with pytest.raises(ValueError):
        await authority_module.build_theme_from_authority_sources("Electrification", "desc", ["https://dead.example.com"], llm, "test-agent")
    assert llm.calls == []  # never even reached the LLM if nothing could be fetched


async def test_multi_source_triggers_merge(fake_llm, monkeypatch):
    async def fake_fetch(url, user_agent, timeout=20.0):
        return {
            "https://a.example.com": "Source A discusses battery manufacturing for electric vehicles.",
            "https://b.example.com": "Source B discusses grid modernization investment.",
        }.get(url)

    monkeypatch.setattr(authority_module, "fetch_source_text", fake_fetch)

    draft_a = _AuthorityActivityDraftList(
        activities=[_AuthorityActivityDraft(name="Battery manufacturing", in_scope_description="x", out_of_scope_description="y", source_quote="battery manufacturing for electric vehicles")]
    )
    draft_b = _AuthorityActivityDraftList(
        activities=[_AuthorityActivityDraft(name="Grid modernization", in_scope_description="x", out_of_scope_description="y", source_quote="grid modernization investment")]
    )

    from arp.research.taxonomy_sources.activity_merge import _MergedActivityDraft, _MergedActivityDraftList

    merged = _MergedActivityDraftList(
        activities=[
            _MergedActivityDraft(name="Battery manufacturing", in_scope_description="x", out_of_scope_description="y"),
            _MergedActivityDraft(name="Grid modernization", in_scope_description="x", out_of_scope_description="y"),
        ],
        merge_notes="Kept both activities distinct; no overlap found.",
    )
    llm = fake_llm({_AuthorityActivityDraftList.__name__: [draft_a, draft_b], _MergedActivityDraftList.__name__: [merged]})

    theme, notes, _usage = await authority_module.build_theme_from_authority_sources(
        "Electrification", "desc", ["https://a.example.com", "https://b.example.com"], llm, "test-agent"
    )
    assert len(theme.activities) == 2
    assert "Kept both activities distinct" in notes
