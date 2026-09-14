from arp.discovery.site_finder import SearchResult
from arp.research.rd_exposure.news_scoring import _AssessmentList, _ResultAssessment, score_news_mentions
from arp.schemas.thematic import ActivityDefinition


def _activity() -> ActivityDefinition:
    return ActivityDefinition(
        name="Solid-state batteries", in_scope_description="Development of solid-state battery technology.", out_of_scope_description=""
    )


async def test_score_news_mentions_empty_results_no_llm_call(fake_llm):
    llm = fake_llm({})
    score, relevant, usage = await score_news_mentions("Acme Motors", _activity(), [], llm)
    assert score == 0.0
    assert relevant == []
    assert usage.input_tokens == 0
    assert llm.calls == []


async def test_score_news_mentions_fraction_relevant(fake_llm):
    results = [
        SearchResult(title="Acme Motors unveils solid-state battery prototype", url="https://example.com/1", snippet="New prototype announced."),
        SearchResult(title="Acme Motors quarterly earnings call transcript", url="https://example.com/2", snippet="Routine earnings."),
        SearchResult(title="Acme Motors partners on solid-state battery R&D", url="https://example.com/3", snippet="New partnership."),
    ]
    draft = _AssessmentList(
        assessments=[
            _ResultAssessment(result_index=0, relevant=True, rationale="Prototype announcement."),
            _ResultAssessment(result_index=1, relevant=False, rationale="Unrelated earnings news."),
            _ResultAssessment(result_index=2, relevant=True, rationale="R&D partnership."),
        ]
    )
    llm = fake_llm({_AssessmentList.__name__: [draft]})

    score, relevant, usage = await score_news_mentions("Acme Motors", _activity(), results, llm)
    assert score == 2 / 3
    assert [r.url for r in relevant] == ["https://example.com/1", "https://example.com/3"]
    assert usage.input_tokens > 0


async def test_score_news_mentions_all_irrelevant(fake_llm):
    results = [SearchResult(title="Unrelated stock news", url="https://example.com/1", snippet="")]
    draft = _AssessmentList(assessments=[_ResultAssessment(result_index=0, relevant=False)])
    llm = fake_llm({_AssessmentList.__name__: [draft]})

    score, relevant, _usage = await score_news_mentions("Acme Motors", _activity(), results, llm)
    assert score == 0.0
    assert relevant == []


async def test_score_news_mentions_out_of_range_index_ignored(fake_llm):
    results = [SearchResult(title="Acme Motors news", url="https://example.com/1")]
    draft = _AssessmentList(assessments=[_ResultAssessment(result_index=99, relevant=True)])
    llm = fake_llm({_AssessmentList.__name__: [draft]})

    score, relevant, _usage = await score_news_mentions("Acme Motors", _activity(), results, llm)
    assert score == 0.0
    assert relevant == []
