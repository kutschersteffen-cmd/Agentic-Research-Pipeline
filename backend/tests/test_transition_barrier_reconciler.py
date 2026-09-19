from __future__ import annotations

import json

from arp.schemas.transition_barrier import AccessPattern, BarrierScore, Rating, RefreshOutcome
from arp.transition_barrier.dataset import load_source_registry
from arp.transition_barrier.refresh.eli import parse_eli
from arp.transition_barrier.refresh.reconciler import (
    FetchedVersion,
    is_auto_applicable,
    partition_findings,
    reconcile,
)
from arp.transition_barrier.refresh.router import automatable_sources, coverage_summary, route_sources

ELI = parse_eli("https://eur-lex.europa.eu/eli/reg/2023/956/oj/eng")


def _score(rating: str = "H", last_verified: str = "2026-08-14") -> BarrierScore:
    return BarrierScore(
        code="STL-R1",
        sector="Steel",
        category="Regulation",
        criterion="Effective carbon price on steel production incl. border adjustment",
        region="European Union",
        rating=rating,
        confidence="high",
        evidence="CBAM in force with free allocation phase-out",
        source="EU CBAM Regulation 2023/956",
        last_verified=last_verified,
    )


# A source_registry.json key, not a credential. It is long and high-entropy
# enough that gitleaks' generic-api-key rule matches it on the `source_key=`
# assignment, so the marker below tells the scanner this one is expected.
_CBAM_SOURCE_KEY = "EU_CBAM_Regulation_2023_956_and_implementing_acts"  # gitleaks:allow


def _fetched(**kwargs) -> FetchedVersion:
    return FetchedVersion(source_key=_CBAM_SOURCE_KEY, eli=ELI, **kwargs)


# --- ELI parsing ------------------------------------------------------------


def test_parses_oj_and_consolidated_eli_uris():
    oj = parse_eli("https://eur-lex.europa.eu/eli/reg/2023/956/oj/eng")
    assert (oj.typ, oj.year, oj.number) == ("reg", 2023, 956)
    assert oj.is_consolidated is False

    consolidated = parse_eli("https://eur-lex.europa.eu/eli/reg/2023/1804/2026-01-08/eng")
    assert consolidated.point_in_time == "2026-01-08"
    assert consolidated.is_consolidated is True
    assert consolidated.celex_like == "reg/2023/1804"


def test_non_eli_urls_do_not_parse():
    assert parse_eli("https://www.iea.org/reports/world-energy-outlook-2024") is None
    assert parse_eli("") is None


def test_celex_links_resolve_to_the_same_act_as_an_eli_uri():
    """FuelEU Maritime is recorded in the registry as a legal-content CELEX
    link rather than an ELI URI. CELEX 32023R1805 is the same act as
    eli/reg/2023/1805, so it must not be written off as un-automatable.
    """
    celex = parse_eli("https://eur-lex.europa.eu/legal-content/en/LSU/?uri=CELEX%3A32023R1805")
    assert celex is not None
    assert celex.celex_like == "reg/2023/1805"
    assert celex.celex_like == parse_eli("https://eur-lex.europa.eu/eli/reg/2023/1805/oj").celex_like
    # 'L' is a directive, not a regulation.
    assert parse_eli("https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32018L2001").typ == "dir"


def test_celex_like_ignores_version_and_language():
    a = parse_eli("https://eur-lex.europa.eu/eli/reg/2023/956/oj/eng")
    b = parse_eli("https://eur-lex.europa.eu/eli/reg/2023/956/2026-01-08/deu")
    assert a.celex_like == b.celex_like


# --- routing ----------------------------------------------------------------


def test_router_only_automates_legal_sources_and_reports_the_rest_honestly():
    routed = route_sources()
    assert len(routed) == 86, "the router must account for every source, not just the automatable ones"

    automatable = automatable_sources()
    assert automatable, "the EUR-Lex slice should find work to do"
    assert all(r.source.access_pattern is AccessPattern.LEGAL_REGULATORY_TEXT for r in automatable)

    non_legal = [r for r in routed if r.source.access_pattern is not AccessPattern.LEGAL_REGULATORY_TEXT]
    assert all(not r.automatable and r.reason for r in non_legal)


def test_coverage_summary_partitions_the_registry():
    summary = coverage_summary()
    assert summary["automatable"] + summary["manual"] == summary["total_sources"] == 86
    legal = [s for s in load_source_registry() if s.access_pattern is AccessPattern.LEGAL_REGULATORY_TEXT]
    assert summary["automatable"] == len(legal) == 15


def test_eurlex_sources_are_scoped_to_the_eu_rating_only():
    """An EU act is evidence about the EU cell, not the US or Chinese one.
    Checking it against all three regions would manufacture two spurious
    findings per criterion.
    """
    from arp.schemas.transition_barrier import Region

    for routed in automatable_sources():
        assert routed.regions == (Region.EUROPEAN_UNION,), routed.source.key


# --- reconciliation ---------------------------------------------------------


def test_unchanged_act_produces_an_unchanged_finding():
    finding = reconcile(_score(), _fetched(in_force=True), recorded_point_in_time="2026-08-14")
    assert finding.outcome is RefreshOutcome.UNCHANGED
    assert finding.proposed_rating is None
    assert finding.needs_review is False


def test_newer_consolidated_version_is_evidence_drift_not_a_rating_change():
    finding = reconcile(
        _score(), _fetched(in_force=True, latest_point_in_time="2027-01-01"), recorded_point_in_time="2026-08-14"
    )
    assert finding.outcome is RefreshOutcome.EVIDENCE_DRIFT
    assert finding.proposed_rating is None
    assert finding.needs_review is False
    assert is_auto_applicable(finding) is True


def test_repealed_act_proposes_a_downgrade_but_only_as_a_candidate():
    """This is the OGU-R1 case: the US methane fee was nullified, so the
    regulatory driver disappeared. The pipeline may propose the downgrade; it
    may never apply it.
    """
    finding = reconcile(_score(rating="H"), _fetched(in_force=False, quote="no longer in force"))
    assert finding.outcome is RefreshOutcome.RATING_CHANGE_CANDIDATE
    assert finding.current_rating is Rating.HIGH
    assert finding.proposed_rating is Rating.MODERATE
    assert finding.needs_review is True
    assert is_auto_applicable(finding) is False


def test_a_repealed_act_under_a_moderate_rating_proposes_low():
    finding = reconcile(_score(rating="M"), _fetched(in_force=False))
    assert finding.proposed_rating is Rating.LOW


def test_conflicting_versions_surface_both_and_propose_nothing():
    """Never silently pick a side when sources disagree."""
    finding = reconcile(_score(), _fetched(in_force=True, conflicting_versions=["2026-01-08", "2027-03-01"]))
    assert finding.outcome is RefreshOutcome.RATING_CHANGE_CANDIDATE
    assert finding.proposed_rating is None
    assert "2026-01-08" in finding.detail and "2027-03-01" in finding.detail
    assert finding.needs_review is True


def test_fetch_failure_is_reported_not_swallowed():
    finding = reconcile(_score(), _fetched(error="timeout"))
    assert finding.outcome is RefreshOutcome.FETCH_FAILED
    assert finding.proposed_rating is None
    assert is_auto_applicable(finding) is False
    # An unverifiable cell is not a verified one -- it must reach a human
    # rather than being silently dropped, or a stale rating passes as checked.
    assert finding.needs_review is True
    assert "timeout" in finding.detail


def test_needs_review_and_is_auto_applicable_are_exact_inverses():
    """These two express the same rule from opposite ends. When they drifted
    apart, the pipeline queued fetch failures for review while the CLI reported
    none -- so pin them across every outcome.
    """
    for fetched in [
        _fetched(in_force=True),
        _fetched(in_force=True, latest_point_in_time="2027-01-01"),
        _fetched(in_force=False),
        _fetched(conflicting_versions=["a", "b"]),
        _fetched(error="boom"),
    ]:
        finding = reconcile(_score(), fetched, recorded_point_in_time="2026-08-14")
        assert is_auto_applicable(finding) is not finding.needs_review, finding.outcome


def test_unknown_in_force_is_not_treated_as_repealed():
    """A fetch that could not determine in-force status must not read as
    'repealed' -- that would manufacture rating-change candidates from noise.
    """
    finding = reconcile(_score(), _fetched(in_force=None), recorded_point_in_time="2026-08-14")
    assert finding.outcome is RefreshOutcome.UNCHANGED


# --- the rule that matters --------------------------------------------------


def test_no_rating_change_is_ever_auto_applicable():
    findings = [
        reconcile(_score(), _fetched(in_force=True), recorded_point_in_time="2026-08-14"),
        reconcile(_score(), _fetched(in_force=True, latest_point_in_time="2027-01-01"), recorded_point_in_time="2026-08-14"),
        reconcile(_score(), _fetched(in_force=False)),
        reconcile(_score(), _fetched(conflicting_versions=["a", "b"])),
        reconcile(_score(), _fetched(error="boom")),
    ]
    auto, review = partition_findings(findings)
    assert len(auto) + len(review) == len(findings)
    assert all(f.proposed_rating is None for f in auto), "an auto-applicable finding must never carry a rating change"
    assert all(f.outcome is not RefreshOutcome.RATING_CHANGE_CANDIDATE for f in auto)
    assert {f.outcome for f in review} == {
        RefreshOutcome.RATING_CHANGE_CANDIDATE,
        RefreshOutcome.FETCH_FAILED,
    }
    assert all(f.needs_review for f in review)


def test_findings_serialise_for_the_review_queue():
    finding = reconcile(_score(), _fetched(in_force=False, quote="repealed"))
    payload = json.loads(json.dumps(finding.model_dump(mode="json")))
    assert payload["outcome"] == "rating_change_candidate"
    assert payload["current_rating"] == "H"
    assert payload["proposed_rating"] == "M"
    assert payload["source_quote"] == "repealed"
