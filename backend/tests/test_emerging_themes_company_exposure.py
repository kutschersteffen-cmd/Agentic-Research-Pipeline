from arp.emerging_themes.company_exposure import compute_company_evidence_quality, compute_company_risk, tags_by_company
from arp.schemas.emerging_themes import ExtractedTag, MaterialityCategory, MentionSourceType, RawMention


def _tag(tag_id: str, mention_id: str, materiality: MaterialityCategory = MaterialityCategory.NONE) -> ExtractedTag:
    return ExtractedTag(tag_id=tag_id, mention_id=mention_id, label="l", claim="c", quote="q", materiality_category=materiality, grounded=True)


def _mention(mention_id: str, url: str) -> RawMention:
    return RawMention(mention_id=mention_id, source_type=MentionSourceType.GDELT, title="t", text="x", url=url)


# --- tags_by_company ---

def test_tags_by_company_groups_by_resolved_company():
    tags = [_tag("t1", "m1"), _tag("t2", "m2"), _tag("t3", "m3")]
    company_ids_by_mention = {"m1": ["acme"], "m2": ["acme", "beta"], "m3": ["beta"]}

    grouped = tags_by_company(tags, company_ids_by_mention)

    assert {t.tag_id for t in grouped["acme"]} == {"t1", "t2"}
    assert {t.tag_id for t in grouped["beta"]} == {"t2", "t3"}


def test_tags_by_company_ignores_unresolved_mentions():
    tags = [_tag("t1", "m1")]
    grouped = tags_by_company(tags, {})
    assert grouped == {}


# --- compute_company_risk ---

def test_company_risk_is_zero_for_empty_input():
    assert compute_company_risk([]) == 0.0


def test_company_risk_is_share_of_risk_category():
    tags = [
        _tag("t1", "m1", materiality=MaterialityCategory.RISK),
        _tag("t2", "m2", materiality=MaterialityCategory.REVENUE),
        _tag("t3", "m3", materiality=MaterialityCategory.NONE),
    ]
    assert compute_company_risk(tags) == 1 / 3


# --- compute_company_evidence_quality ---

def test_evidence_quality_is_zero_for_empty_input():
    assert compute_company_evidence_quality([], {}, min_independent_sources=2) == 0.0


def test_evidence_quality_is_zero_for_zero_threshold():
    tags = [_tag("t1", "m1")]
    mentions_by_id = {"m1": _mention("m1", "https://a.example.com")}
    assert compute_company_evidence_quality(tags, mentions_by_id, min_independent_sources=0) == 0.0


def test_evidence_quality_is_normalized_below_threshold():
    tags = [_tag("t1", "m1")]
    mentions_by_id = {"m1": _mention("m1", "https://a.example.com")}
    assert compute_company_evidence_quality(tags, mentions_by_id, min_independent_sources=2) == 0.5


def test_evidence_quality_is_capped_at_one_above_threshold():
    tags = [_tag("t1", "m1"), _tag("t2", "m2"), _tag("t3", "m3")]
    mentions_by_id = {
        "m1": _mention("m1", "https://a.example.com"),
        "m2": _mention("m2", "https://b.example.com"),
        "m3": _mention("m3", "https://c.example.com"),
    }
    assert compute_company_evidence_quality(tags, mentions_by_id, min_independent_sources=2) == 1.0
