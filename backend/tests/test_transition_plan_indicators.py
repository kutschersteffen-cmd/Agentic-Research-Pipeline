from arp.schemas.transition_plan import IndicatorCategory, WalkOrTalk
from arp.transition_plan.indicators import load_indicators


def test_loads_all_64_paper_indicators():
    indicators = load_indicators()
    assert len(indicators) == 64
    assert len({i.identifier for i in indicators}) == 64
    assert [i.number for i in indicators] == list(range(1, 65))


def test_walk_talk_split_matches_paper():
    # The paper states 34 of 64 indicators are classified "Walk" and 30 "Talk".
    indicators = load_indicators()
    walk = sum(1 for i in indicators if i.walk_or_talk == WalkOrTalk.WALK)
    talk = sum(1 for i in indicators if i.walk_or_talk == WalkOrTalk.TALK)
    assert walk == 34
    assert talk == 30


def test_category_counts_match_paper_tables():
    # Table S.2 (Target)=12, S.3 (Governance)=9, S.4 (Strategy)=24, S.5 (Tracking)=19.
    indicators = load_indicators()
    counts = {cat: sum(1 for i in indicators if i.category == cat) for cat in IndicatorCategory}
    assert counts[IndicatorCategory.TARGET] == 12
    assert counts[IndicatorCategory.GOVERNANCE] == 9
    assert counts[IndicatorCategory.STRATEGY] == 24
    assert counts[IndicatorCategory.TRACKING] == 19


def test_every_indicator_has_question_and_guideline():
    for i in load_indicators():
        assert i.question.strip()
        assert i.guideline.strip()
