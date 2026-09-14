from arp.research.taxonomy_sources.bundled_sources import bundled_source_categories, list_bundled_authority_sources
from arp.schemas.taxonomy_sources import SourceCandidateType


def test_list_bundled_authority_sources_returns_well_formed_candidates():
    sources = list_bundled_authority_sources()
    assert len(sources) > 0
    for candidate in sources:
        assert candidate.source_type == SourceCandidateType.AUTHORITY
        assert candidate.url.startswith("https://")
        assert candidate.name
        assert candidate.authority_score == 1.0


def test_list_bundled_authority_sources_covers_expected_categories():
    categories = set(bundled_source_categories())
    assert {"eu_taxonomy", "nace", "iea", "ipcc"} <= categories


def test_list_bundled_authority_sources_filters_by_category():
    nace_sources = list_bundled_authority_sources(category="nace")
    assert len(nace_sources) > 0
    assert all("nace" in c.name.lower() or "nace" in c.snippet.lower() for c in nace_sources)

    unknown = list_bundled_authority_sources(category="not_a_real_category")
    assert unknown == []
