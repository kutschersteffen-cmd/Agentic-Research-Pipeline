import pytest

from arp.research.activity_generator import _ActivityDraft, _ActivityDraftList
from arp.research.taxonomy_sources import authority as authority_module


async def test_build_theme_from_authority_sources_grounds_on_fetched_text(fake_llm, monkeypatch):
    async def fake_fetch(url, user_agent, timeout=20.0):
        if url == "https://iea.org/taxonomy":
            return "The IEA defines electrification as the direct use of electricity in end-use sectors."
        return None  # this one fails to fetch

    monkeypatch.setattr(authority_module, "fetch_source_text", fake_fetch)

    draft = _ActivityDraftList(
        activities=[
            _ActivityDraft(name="Direct electrification", in_scope_description="x", out_of_scope_description="y", seed_keywords=["electrification"])
        ]
    )
    llm = fake_llm({_ActivityDraftList.__name__: [draft]})

    theme, notes, usage = await authority_module.build_theme_from_authority_sources(
        "Electrification", "desc", ["https://iea.org/taxonomy", "https://dead-link.example.com"], llm, "test-agent"
    )
    assert theme.name == "Electrification"
    assert len(theme.activities) == 1
    assert "iea.org/taxonomy" in notes
    assert "dead-link.example.com" in notes  # noted as unfetchable, not silently dropped
    assert usage.input_tokens > 0

    # the fetched IEA text should have made it into the prompt sent to the model
    assert "direct use of electricity" in llm.prompts[0]


async def test_build_theme_from_authority_sources_all_fail_raises(fake_llm, monkeypatch):
    async def fake_fetch(url, user_agent, timeout=20.0):
        return None

    monkeypatch.setattr(authority_module, "fetch_source_text", fake_fetch)
    llm = fake_llm({})

    with pytest.raises(ValueError):
        await authority_module.build_theme_from_authority_sources("Electrification", "desc", ["https://dead.example.com"], llm, "test-agent")
    assert llm.calls == []  # never even reached the LLM if there was nothing to ground on
