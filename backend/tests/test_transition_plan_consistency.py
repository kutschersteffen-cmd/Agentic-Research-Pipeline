from arp.schemas.transition_plan import IndicatorAssessment, IndicatorCategory, Verdict, WalkOrTalk
from arp.transition_plan.aggregator import REQUIRES_YES, apply_consistency_rules
from arp.transition_plan.indicators import load_indicators


def _a(identifier: str, verdict: Verdict, notes: str | None = None) -> IndicatorAssessment:
    return IndicatorAssessment(
        number=1, identifier=identifier, category=IndicatorCategory.TARGET, walk_or_talk=WalkOrTalk.TALK,
        question="q", verdict=verdict, confidence=0.9, verifier_notes=notes,
    )


def test_rules_name_real_indicators():
    ids = {i.identifier for i in load_indicators()}
    assert set(REQUIRES_YES) <= ids
    assert set(REQUIRES_YES.values()) <= ids


def test_child_yes_with_parent_no_is_forced_no_and_reviewed():
    out = apply_consistency_rules([_a("A_ambition_3", Verdict.NO), _a("A_ambition_4", Verdict.YES, "agreed")])
    child = out[1]
    assert child.verdict == Verdict.NO
    assert child.needs_review
    assert child.verifier_notes.startswith("agreed Forced NO: A_ambition_3")
    assert out[0].verdict == Verdict.NO and not out[0].needs_review


def test_parent_yes_na_or_missing_leaves_child_alone():
    for parent in ([_a("A_ambition_3", Verdict.YES)], [_a("A_ambition_3", Verdict.NA)], []):
        out = apply_consistency_rules([*parent, _a("A_ambition_4", Verdict.YES)])
        assert out[-1].verdict == Verdict.YES and not out[-1].needs_review


def test_child_no_or_na_is_untouched():
    for v in (Verdict.NO, Verdict.NA):
        out = apply_consistency_rules([_a("A_headline_1", Verdict.NO), _a("A_coverage_6", v)])
        assert out[1].verdict == v and not out[1].needs_review
