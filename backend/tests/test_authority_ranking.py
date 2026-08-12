from arp.research.taxonomy_sources.discovery import _AssessmentList, _CandidateAssessment, rank_authority_sources
from arp.schemas.taxonomy_sources import SourceCandidate, SourceCandidateType


def _candidate(name: str, url: str) -> SourceCandidate:
    return SourceCandidate(source_type=SourceCandidateType.AUTHORITY, name=name, url=url, snippet="")


async def test_rank_authority_sources_sorts_by_score(fake_llm):
    candidates = [_candidate("Blog post", "https://blog.example.com/x"), _candidate("IEA report", "https://iea.org/x")]
    assessments = _AssessmentList(
        assessments=[
            _CandidateAssessment(candidate_id=candidates[0].candidate_id, authority_score=0.2, authority_reasoning="A marketing blog, not authoritative."),
            _CandidateAssessment(candidate_id=candidates[1].candidate_id, authority_score=0.95, authority_reasoning="IEA is an intergovernmental energy agency."),
        ]
    )
    llm = fake_llm({_AssessmentList.__name__: [assessments]})

    ranked, usage = await rank_authority_sources("Electrification", candidates, llm)
    assert [c.name for c in ranked] == ["IEA report", "Blog post"]
    assert ranked[0].authority_score == 0.95
    assert "intergovernmental" in ranked[0].authority_reasoning
    assert usage.input_tokens > 0


async def test_rank_authority_sources_empty_list_skips_llm(fake_llm):
    llm = fake_llm({})
    ranked, usage = await rank_authority_sources("Electrification", [], llm)
    assert ranked == []
    assert llm.calls == []


async def test_unassessed_candidate_is_kept_unranked(fake_llm):
    """If the model's response omits a candidate_id, that candidate should
    still be returned (defensively), not dropped."""
    candidates = [_candidate("Source A", "https://a.example.com"), _candidate("Source B", "https://b.example.com")]
    assessments = _AssessmentList(
        assessments=[_CandidateAssessment(candidate_id=candidates[0].candidate_id, authority_score=0.5, authority_reasoning="ok")]
    )
    llm = fake_llm({_AssessmentList.__name__: [assessments]})

    ranked, _usage = await rank_authority_sources("Theme", candidates, llm)
    assert len(ranked) == 2
    names = {c.name for c in ranked}
    assert names == {"Source A", "Source B"}
