from arp.research.taxonomy_sources.corpus_synthesis import (
    _SynthesizedActivityDraft,
    _SynthesizedActivityDraftList,
    synthesize_activities_from_corpus,
)
from arp.schemas.taxonomy_sources import CorpusSnippet, CorpusSourceType


async def test_synthesize_activities_from_corpus(fake_llm):
    corpus = [
        CorpusSnippet(text="We manufacture EV battery packs.", source_type=CorpusSourceType.EXTRACTION_ENGINE, source_ref="c1"),
        CorpusSnippet(text="Our grid modernization segment grew 20%.", source_type=CorpusSourceType.NEWS, source_ref="https://example.com/a"),
    ]
    draft = _SynthesizedActivityDraftList(
        activities=[
            _SynthesizedActivityDraft(
                name="EV battery manufacturing", in_scope_description="Makes battery packs", out_of_scope_description="Non-EV batteries",
                seed_keywords=["battery pack"],
            ),
            _SynthesizedActivityDraft(
                name="Grid modernization", in_scope_description="Upgrades grid infrastructure", out_of_scope_description="Non-grid utilities",
                seed_keywords=["grid modernization"],
            ),
        ],
        corpus_assessment="Corpus supports two clear, distinct activities.",
    )
    llm = fake_llm({_SynthesizedActivityDraftList.__name__: [draft]})

    activities, assessment, usage = await synthesize_activities_from_corpus("Electrification", "desc", corpus, llm)
    assert [a.name for a in activities] == ["EV battery manufacturing", "Grid modernization"]
    assert "two clear" in assessment
    assert usage.input_tokens > 0


async def test_synthesize_truncates_corpus_to_max_snippets(fake_llm):
    corpus = [
        CorpusSnippet(text=f"snippet-marker-{i}", source_type=CorpusSourceType.NEWS, source_ref=f"ref{i}") for i in range(100)
    ]
    draft = _SynthesizedActivityDraftList(activities=[], corpus_assessment="thin corpus")
    llm = fake_llm({_SynthesizedActivityDraftList.__name__: [draft]})

    activities, assessment, _usage = await synthesize_activities_from_corpus("Theme", "desc", corpus, llm, max_snippets=5)
    assert activities == []
    assert assessment == "thin corpus"
    sent_prompt = llm.prompts[0]
    assert "snippet-marker-4" in sent_prompt
    assert "snippet-marker-5" not in sent_prompt  # only the first 5 (indices 0-4) should be included
