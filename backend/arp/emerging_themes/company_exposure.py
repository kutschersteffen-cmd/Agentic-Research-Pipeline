from __future__ import annotations

from arp.emerging_themes.synthesis import independent_source_count
from arp.schemas.emerging_themes import ExtractedTag, MaterialityCategory, RawMention


def tags_by_company(member_tags: list[ExtractedTag], company_ids_by_mention: dict[str, list[str]]) -> dict[str, list[ExtractedTag]]:
    """Groups a cluster's member tags by which companies their mention
    resolved to -- a tag whose mention resolved to multiple companies
    appears under each, since the underlying claim is genuinely evidence
    for all of them."""
    grouped: dict[str, list[ExtractedTag]] = {}
    for tag in member_tags:
        for company_id in company_ids_by_mention.get(tag.mention_id, []):
            grouped.setdefault(company_id, []).append(tag)
    return grouped


def compute_company_risk(company_tags: list[ExtractedTag]) -> float:
    """Share of this company's own tags whose materiality_category is
    RISK -- a narrower slice of scoring.py::compute_materiality (which
    counts every non-NONE category), scoped to one company instead of a
    whole cluster. Empty input scores 0.0."""
    if not company_tags:
        return 0.0
    risk_count = sum(1 for tag in company_tags if tag.materiality_category == MaterialityCategory.RISK)
    return risk_count / len(company_tags)


def compute_company_evidence_quality(company_tags: list[ExtractedTag], mentions_by_id: dict[str, RawMention], min_independent_sources: int) -> float:
    """This company's own independent-source count, normalized against
    the promotion threshold -- not "share grounded", since every
    surviving ExtractedTag is already grounded by construction
    (extraction.py::tag_mention drops ungrounded ones before they exist),
    so that share would always read 1.0 and isn't a useful signal here.
    Empty input, or a zero threshold, scores 0.0."""
    if not company_tags or min_independent_sources <= 0:
        return 0.0
    source_count = independent_source_count(company_tags, mentions_by_id)
    return min(1.0, source_count / min_independent_sources)
