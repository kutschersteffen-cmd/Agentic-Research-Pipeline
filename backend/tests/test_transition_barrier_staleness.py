from __future__ import annotations

from datetime import date

from arp.schemas.transition_barrier import BarrierScore
from arp.transition_barrier.dataset import load_scores
from arp.transition_barrier.staleness import (
    DEFAULT_STALENESS_DAYS,
    build_staleness_report,
    is_stale,
    stale_scores,
    staleness_days,
)

VERIFIED = "2026-08-14"


def _score(*, confidence: str = "high", last_verified: str = VERIFIED, code: str = "PWR-T1") -> BarrierScore:
    return BarrierScore(
        code=code,
        sector="Power & Utilities",
        category="Technology",
        criterion="Levelised cost of renewable generation vs. new-build fossil",
        region="European Union",
        rating="H",
        confidence=confidence,
        evidence="evidence",
        source="source",
        last_verified=last_verified,
    )


def test_staleness_days_counts_from_last_verified():
    assert staleness_days(_score(), now=date(2026, 8, 14)) == 0
    assert staleness_days(_score(), now=date(2026, 8, 24)) == 10
    assert staleness_days(_score(), now=date(2027, 8, 14)) == 365


def test_threshold_is_inclusive_at_18_months():
    score = _score()
    assert DEFAULT_STALENESS_DAYS == 548

    # 2026-08-14 + 548 days lands on 2028-02-13, the first stale day.
    assert staleness_days(score, now=date(2028, 2, 13)) == 548
    assert is_stale(score, now=date(2028, 2, 13)) is True
    assert is_stale(score, now=date(2028, 2, 12)) is False


def test_staleness_is_independent_of_confidence():
    """The rule this module exists for: a high-confidence rating that has not
    been re-checked in 18 months is stale, not low-confidence. Collapsing the
    two would hide exactly the case the refresh pipeline is meant to catch.
    """
    old_and_confident = _score(confidence="high", last_verified="2020-01-01")
    fresh_and_unsure = _score(confidence="low", last_verified="2026-08-14")

    assert is_stale(old_and_confident, now=date(2026, 9, 15)) is True
    assert old_and_confident.confidence.value == "high"

    assert is_stale(fresh_and_unsure, now=date(2026, 9, 15)) is False
    assert fresh_and_unsure.confidence.value == "low"


def test_report_counts_partition_the_input():
    rows = [_score(code="PWR-T1", last_verified="2020-01-01"), _score(code="PWR-T2", last_verified="2026-08-14")]
    report = build_staleness_report(now=date(2026, 9, 15), scores=rows)
    assert report.total == 2
    assert report.stale + report.fresh == report.total
    assert report.stale == 1
    assert report.stale_codes == ["PWR-T1"]


def test_bundled_matrix_is_within_threshold_shortly_after_verification():
    """Every bundled cell was verified 2026-08-14, so at one year out none is
    stale yet -- and the whole matrix tips over together in Feb 2028.
    """
    rows = load_scores()
    assert stale_scores(now=date(2027, 8, 14), scores=rows) == []
    assert len(stale_scores(now=date(2028, 2, 13), scores=rows)) == len(rows)


def test_threshold_override_is_honoured():
    rows = load_scores()
    report = build_staleness_report(threshold_days=30, now=date(2026, 9, 15), scores=rows)
    assert report.stale == len(rows)
    assert report.threshold_days == 30
