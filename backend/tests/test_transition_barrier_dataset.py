from __future__ import annotations

import collections
import re

from arp.schemas.transition_barrier import CRITERION_CODE_PATTERN, AccessPattern, Pillar, Region
from arp.transition_barrier.dataset import (
    build_matrix,
    criteria_by_code,
    filter_scores,
    load_criteria,
    load_scores,
    load_source_registry,
    rating_distribution,
    sectors,
    sources_for_criterion,
)

# Sector -> criterion count, straight from the research tool's Criteria
# Reference sheet. Pinned so a bad edit to the bundled JSON fails loudly
# rather than silently shrinking the matrix.
EXPECTED_SECTOR_COUNTS = {
    "Power & Utilities": 5,
    "Steel": 5,
    "Cement": 5,
    "Chemicals": 4,
    "Critical Minerals & Mining": 4,
    "Aviation": 3,
    "Shipping": 3,
    "Heavy-Duty Road Transport": 3,
    "Oil & Gas Upstream": 3,
}

EXPECTED_ACCESS_PATTERN_COUNTS = {
    AccessPattern.PERIODIC_PDF_REPORT: 27,
    AccessPattern.GOVERNMENT_AGENCY_PUBLICATION: 21,
    AccessPattern.LEGAL_REGULATORY_TEXT: 15,
    AccessPattern.INDUSTRY_TRACKER_DATABASE: 10,
    AccessPattern.COMPANY_DISCLOSURE: 7,
    AccessPattern.STRUCTURED_API_OR_DASHBOARD: 6,
}


def test_loads_35_criteria_with_expected_sector_and_pillar_split():
    criteria = load_criteria()
    assert len(criteria) == 35
    assert collections.Counter(c.sector for c in criteria) == EXPECTED_SECTOR_COUNTS
    assert collections.Counter(c.category for c in criteria) == {
        Pillar.TECHNOLOGY: 13,
        Pillar.REGULATION: 13,
        Pillar.DEMAND_ECONOMICS: 9,
    }
    assert len(sectors()) == 9


def test_every_criterion_code_is_normalised_and_unique():
    codes = [c.code for c in load_criteria()]
    assert len(set(codes)) == 35
    # Shipping originally used underscores (SHP_T1); normalised on import.
    assert all(re.match(CRITERION_CODE_PATTERN, code) for code in codes)
    assert "SHP-T1" in codes and "SHP_T1" not in codes


def test_every_criterion_has_a_complete_hml_rubric_and_at_least_one_source():
    for criterion in load_criteria():
        assert set(criterion.rating_rubric) == {"H", "M", "L"}, criterion.code
        assert all(text.strip() for text in criterion.rating_rubric.values()), criterion.code
        assert criterion.metric.strip() and criterion.unit.strip(), criterion.code
        assert criterion.primary_sources, criterion.code


def test_105_scores_cover_every_criterion_in_all_three_regions():
    scores = load_scores()
    assert len(scores) == 105
    per_code = collections.Counter(s.code for s in scores)
    assert set(per_code) == set(criteria_by_code())
    assert set(per_code.values()) == {3}, "every criterion must be rated in all three regions"
    for code in per_code:
        assert {s.region for s in filter_scores(code=code)} == set(Region)


def test_every_score_carries_evidence_and_a_source():
    for score in load_scores():
        assert score.evidence.strip(), f"{score.code}/{score.region.value} has no evidence"
        assert score.source.strip(), f"{score.code}/{score.region.value} has no source"
        assert score.last_verified


def test_rating_distribution_matches_the_verified_matrix():
    assert rating_distribution() == {"H": 24, "M": 49, "L": 32}
    assert rating_distribution(Region.EUROPEAN_UNION) == {"H": 16, "M": 16, "L": 3}
    assert rating_distribution(Region.UNITED_STATES) == {"H": 3, "M": 22, "L": 10}
    assert rating_distribution(Region.CHINA) == {"H": 5, "M": 11, "L": 19}
    assert sum(rating_distribution().values()) == 105


def test_matrix_is_35_by_3():
    grid = build_matrix()
    assert len(grid) == 35
    assert all(len(by_region) == 3 for by_region in grid.values())
    assert sum(len(v) for v in grid.values()) == 105


def test_source_registry_shape_and_access_pattern_split():
    sources = load_source_registry()
    assert len(sources) == 86
    assert len({s.key for s in sources}) == 86
    assert collections.Counter(s.access_pattern for s in sources) == EXPECTED_ACCESS_PATTERN_COUNTS


def test_only_company_disclosure_sources_lack_a_url():
    """The 7 company_disclosure entries have no single URL by design -- which
    company matters depends on who is being assessed. Every other source must
    carry one.
    """
    without_url = {s.key for s in load_source_registry() if not s.url}
    company_disclosure = {s.key for s in load_source_registry() if s.access_pattern is AccessPattern.COMPANY_DISCLOSURE}
    assert without_url == company_disclosure
    assert len(without_url) == 7


def test_registry_never_references_an_unknown_criterion():
    known = set(criteria_by_code())
    for source in load_source_registry():
        assert source.used_by_criteria, f"{source.key} is used by no criterion"
        unknown = set(source.used_by_criteria) - known
        assert not unknown, f"{source.key} references unknown criteria: {unknown}"


def test_every_criterion_resolves_to_at_least_one_registry_source():
    for criterion in load_criteria():
        assert sources_for_criterion(criterion.code), f"{criterion.code} resolves to no registry source"


def test_filter_scores_ands_its_arguments():
    rows = filter_scores(region=Region.CHINA, pillar=Pillar.REGULATION)
    assert rows
    assert all(r.region is Region.CHINA and r.category is Pillar.REGULATION for r in rows)
    assert len(rows) == 13


def test_the_two_2025_us_policy_reversals_are_present():
    """MIN-R2 and OGU-R1 (US) moved during verification because US federal
    policy reversed in 2025. They are the worked example for why the refresh
    pipeline searches for policy change rather than just re-fetching a page,
    so their presence is worth asserting directly.
    """
    min_r2 = next(s for s in filter_scores(code="MIN-R2") if s.region is Region.UNITED_STATES)
    ogu_r1 = next(s for s in filter_scores(code="OGU-R1") if s.region is Region.UNITED_STATES)
    assert min_r2.rating.value == "M"
    assert "One Big Beautiful Bill" in min_r2.evidence or "30D" in min_r2.evidence
    assert ogu_r1.rating.value == "L"
    assert "Congressional Review Act" in ogu_r1.evidence or "Waste Emissions Charge" in ogu_r1.evidence
