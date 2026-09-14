from arp.emerging_themes.synthesis import _CandidateDraft, build_candidate, independent_source_count
from arp.schemas.emerging_themes import CandidateStatus, ExtractedTag, MentionSourceType, RawMention, TopicCluster


def _mention(mention_id: str, url: str) -> RawMention:
    return RawMention(mention_id=mention_id, source_type=MentionSourceType.GDELT, title="t", text="x", url=url)


def _tag(tag_id: str, mention_id: str, grounded: bool = True) -> ExtractedTag:
    return ExtractedTag(tag_id=tag_id, mention_id=mention_id, label="solid-state battery", claim="claim", quote="quote", grounded=grounded)


def _cluster() -> TopicCluster:
    return TopicCluster(cluster_id="cl1", period="2026-W01", representative_label="solid-state battery", company_ids=["acme"], mention_count=3)


def test_independent_source_count_dedupes_by_url_and_ignores_ungrounded():
    mentions_by_id = {"m1": _mention("m1", "https://a.example.com"), "m2": _mention("m2", "https://a.example.com"), "m3": _mention("m3", "https://b.example.com")}
    tags = [_tag("t1", "m1"), _tag("t2", "m2"), _tag("t3", "m3"), _tag("t4", "m3", grounded=False)]

    count = independent_source_count(tags, mentions_by_id)

    assert count == 2  # m1 and m2 share a URL, so only a+b count as distinct


async def test_below_minimum_independent_sources_returns_none_without_llm_call(fake_llm):
    mentions_by_id = {"m1": _mention("m1", "https://a.example.com")}
    tags = [_tag("t1", "m1")]
    llm = fake_llm({})

    candidate, _usage = await build_candidate(_cluster(), tags, mentions_by_id, llm, "run1", min_independent_sources=2)

    assert candidate is None
    assert llm.calls == []


async def test_sufficient_sources_produces_candidate(fake_llm):
    mentions_by_id = {"m1": _mention("m1", "https://a.example.com"), "m2": _mention("m2", "https://b.example.com")}
    tags = [_tag("t1", "m1"), _tag("t2", "m2")]
    draft = _CandidateDraft(
        theme_name="Solid-state battery commercialization",
        description="Companies are commercializing solid-state battery cells.",
        economic_rationale="A step-change in energy density would reshape EV cost structures.",
        rationale="Two independent sources report solid-state battery progress.",
    )
    llm = fake_llm({"_CandidateDraft": [draft]})

    candidate, _usage = await build_candidate(_cluster(), tags, mentions_by_id, llm, "run1", min_independent_sources=2)

    assert candidate is not None
    assert candidate.theme_name == "Solid-state battery commercialization"
    assert candidate.status == CandidateStatus.CANDIDATE
    assert candidate.candidate_sectors_companies == ["acme"]
    assert len(candidate.corroborating_sources) == 2
    assert candidate.economic_rationale.startswith("A step-change")
