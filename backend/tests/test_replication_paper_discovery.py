from arp.discovery.site_finder import SearchResult
from arp.replication.paper_discovery import discover_candidate_papers, rank_candidate_papers
from arp.schemas.paper_discovery import PaperCandidate
from arp.schemas.strategy_replication import SignalType


async def test_discover_candidate_papers_dedupes_urls_across_query_templates(fake_search):
    # Every query template contains "{topic}", so a FakeSearchClient keyed on the topic string matches
    # (and returns the same result set for) every one of the 4 templates -- exercising the dedup-by-URL logic.
    results = [
        SearchResult(title="Momentum Paper A", url="https://ssrn.com/a", snippet="finds momentum anomaly"),
        SearchResult(title="Momentum Paper B", url="https://ssrn.com/b", snippet="cross-section returns"),
    ]
    search_client = fake_search({"momentum": results})
    candidates = await discover_candidate_papers("momentum", search_client, max_candidates=10)
    urls = [c.url for c in candidates]
    assert urls.count("https://ssrn.com/a") == 1
    assert urls.count("https://ssrn.com/b") == 1
    assert len(search_client.queries) == 4  # one query per template, all matched


async def test_discover_candidate_papers_respects_max_candidates(fake_search):
    results = [SearchResult(title=f"Paper {i}", url=f"https://ssrn.com/{i}", snippet="") for i in range(20)]
    search_client = fake_search({"value": results})
    candidates = await discover_candidate_papers("value", search_client, max_candidates=3)
    assert len(candidates) == 3


async def test_discover_candidate_papers_no_results_returns_empty(fake_search):
    search_client = fake_search({})
    candidates = await discover_candidate_papers("nonsense topic", search_client)
    assert candidates == []


async def test_rank_candidate_papers_empty_input_returns_empty(fake_llm):
    llm = fake_llm({})
    ranked, usage = await rank_candidate_papers("momentum", [], llm)
    assert ranked == []
    assert usage.input_tokens == 0


async def test_rank_candidate_papers_sorts_by_score_descending(fake_llm):
    candidates = [
        PaperCandidate(candidate_id="p1", title="Low score paper", url="https://x.com/1"),
        PaperCandidate(candidate_id="p2", title="High score paper", url="https://x.com/2"),
    ]
    from arp.replication.paper_discovery import _AssessmentList, _CandidateAssessment

    assessment = _AssessmentList(
        assessments=[
            _CandidateAssessment(candidate_id="p1", replication_worthiness_score=0.2, worthiness_reasoning="weak", suggested_signal_type=None),
            _CandidateAssessment(
                candidate_id="p2", replication_worthiness_score=0.9, worthiness_reasoning="strong", suggested_signal_type=SignalType.MOMENTUM
            ),
        ]
    )
    llm = fake_llm({"_AssessmentList": [assessment]})
    ranked, _usage = await rank_candidate_papers("momentum", candidates, llm)
    assert [c.candidate_id for c in ranked] == ["p2", "p1"]
    assert ranked[0].suggested_signal_type == SignalType.MOMENTUM
    assert ranked[1].worthiness_reasoning == "weak"
