from arp.research.results_diff import diff_theme_results
from arp.schemas.thematic import CompanyMatch, ExposureEstimate, MatchVerdict


def _match(company_id="c1", activity_id="act1", verdict=MatchVerdict.INCLUDE, confidence=0.8) -> CompanyMatch:
    return CompanyMatch(
        company_id=company_id, name="Acme", activity_id=activity_id, activity_name="EV manufacturing",
        verdict=verdict, exposure_estimate=ExposureEstimate.SIGNIFICANT, confidence=confidence,
        adjudicator_rationale="x",
    )


def test_added_and_dropped_keys():
    a = [_match(company_id="c1"), _match(company_id="c2")]
    b = [_match(company_id="c2"), _match(company_id="c3")]
    diff = diff_theme_results("run_a", "run_b", a, b)
    assert diff.added == ["c3:act1"]
    assert diff.dropped == ["c1:act1"]


def test_verdict_changed_detected():
    a = [_match(verdict=MatchVerdict.EXCLUDE, confidence=0.9)]
    b = [_match(verdict=MatchVerdict.INCLUDE, confidence=0.9)]
    diff = diff_theme_results("run_a", "run_b", a, b)
    assert len(diff.verdict_changed) == 1
    entry = diff.verdict_changed[0]
    assert entry.old_verdict == MatchVerdict.EXCLUDE
    assert entry.new_verdict == MatchVerdict.INCLUDE
    assert diff.confidence_changed == []


def test_confidence_changed_detected_when_verdict_same():
    a = [_match(confidence=0.5)]
    b = [_match(confidence=0.9)]
    diff = diff_theme_results("run_a", "run_b", a, b, confidence_delta_threshold=0.1)
    assert diff.verdict_changed == []
    assert len(diff.confidence_changed) == 1
    assert diff.confidence_changed[0].old_confidence == 0.5
    assert diff.confidence_changed[0].new_confidence == 0.9


def test_small_confidence_delta_below_threshold_is_unchanged():
    a = [_match(confidence=0.80)]
    b = [_match(confidence=0.85)]
    diff = diff_theme_results("run_a", "run_b", a, b, confidence_delta_threshold=0.1)
    assert diff.confidence_changed == []
    assert diff.unchanged_count == 1


def test_identical_results_are_all_unchanged():
    a = [_match(company_id="c1"), _match(company_id="c2")]
    b = [_match(company_id="c1"), _match(company_id="c2")]
    diff = diff_theme_results("run_a", "run_b", a, b)
    assert diff.added == []
    assert diff.dropped == []
    assert diff.verdict_changed == []
    assert diff.confidence_changed == []
    assert diff.unchanged_count == 2


def test_diff_keys_by_company_and_activity_together():
    a = [_match(company_id="c1", activity_id="act1")]
    b = [_match(company_id="c1", activity_id="act2")]  # same company, different activity -- not the same key
    diff = diff_theme_results("run_a", "run_b", a, b)
    assert diff.added == ["c1:act2"]
    assert diff.dropped == ["c1:act1"]
