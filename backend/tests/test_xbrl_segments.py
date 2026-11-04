from __future__ import annotations

from arp.ingestion.esef import DimFact
from arp.xbrl_pipeline.segments import build_segments, sec_segments, segment_name
from tests.segment_fixture import FY24, FY25, Q4, REV, fixture_s, ixbrl, seg

ELIM = {"srt:ConsolidationItemsAxis": "us-gaap:IntersegmentEliminationMember"}
OPSEG = {"srt:ConsolidationItemsAxis": "us-gaap:OperatingSegmentsMember"}


def _rows(facts):
    return sec_segments(ixbrl(facts), company_id="s1", accession="a1")[0]


def _vals(rows, metric):
    return [(r.member, r.value) for r in rows if r.metric == metric]


def test_fixture_s_three_rows():
    rows = _rows(fixture_s())
    assert _vals(rows, "revenue") == [("x:AlphaSegmentMember", 300), ("x:BetaMember", 400), ("x:GammaSegmentMember", 295)]
    assert {(r.unit, r.fiscal_year, r.market, r.concept) for r in rows} == {("USD", 2025, "sec", REV)}


def test_ac_3_intersegment_elimination_dropped():
    assert len(_rows(fixture_s(extra=[seg("x:AlphaSegmentMember", -50, extra=ELIM)]))) == 3


def test_ac_4_product_axis_dropped():
    rows = [r for r in _rows(fixture_s(extra=[(REV, {"srt:ProductOrServiceAxis": "x:PhoneMember"}, 500, FY25)]))
            if r.axis_kind == "segment"]  # product rows are kept since the product/geography spec
    assert len(rows) == 3 and all(r.axis != "srt:ProductOrServiceAxis" for r in rows)


def test_ac_5_quarter_dropped():
    rows = _rows(fixture_s(extra=[seg("x:AlphaSegmentMember", 80, period=Q4)]))
    assert len(rows) == 3 and rows[0].value == 300


def test_ac_6_prior_year_dropped():
    prior = [seg(m, 1, period=FY24) for m in ("x:AlphaSegmentMember", "x:BetaMember", "x:GammaSegmentMember")]
    rows = _rows(fixture_s(extra=prior))
    assert len(rows) == 3 and {r.fiscal_year for r in rows} == {2025}


def test_ac_7_first_concept_wins():
    rows = _rows(fixture_s(extra=[seg("x:AlphaSegmentMember", 9, concept="us-gaap:Revenues")]))
    assert {r.concept for r in rows} == {REV}


def test_ac_8_sum_within_one_percent():
    assert all(r.sum_matches_total for r in _rows(fixture_s()))


def test_ac_9_sum_too_low():
    assert not any(r.sum_matches_total for r in _rows(fixture_s(gamma=275)))


def test_ac_10_sum_too_high():
    assert not any(r.sum_matches_total for r in _rows(fixture_s(gamma=320)))


def test_ac_11_no_total():
    assert not any(r.sum_matches_total for r in _rows(fixture_s(total=None)))


def test_ac_12_segment_names():
    assert [r.segment for r in _rows(fixture_s())] == ["Alpha", "Beta", "Gamma"]


def test_ac_22_capex():
    PP = "us-gaap:PaymentsToAcquireProductiveAssets"
    rows = _rows(fixture_s(extra=[seg("x:AlphaSegmentMember", 50, PP), seg("x:BetaMember", 70, PP)]))
    assert [r.value for r in rows if r.metric == "capex"] == [50, 70]
    assert _vals(rows, "revenue") == _vals(_rows(fixture_s()), "revenue")


def test_ac_23_rnd():
    RD = "us-gaap:ResearchAndDevelopmentExpense"
    rows = _rows(fixture_s(extra=[seg("x:AlphaSegmentMember", 20, RD), seg("x:BetaMember", 30, RD)]))
    assert [r.value for r in rows if r.metric == "rnd"] == [20, 30]


OPEX = [seg("x:AlphaSegmentMember", 100, "us-gaap:OperatingExpenses"), seg("x:BetaMember", 120, "us-gaap:OperatingExpenses")]


def test_ac_24_opex():
    assert [r.value for r in _rows(fixture_s(extra=OPEX)) if r.metric == "opex"] == [100, 120]


def test_ac_25_cost_of_revenue():
    rows = _rows(fixture_s(extra=[seg("x:AlphaSegmentMember", 150, "us-gaap:CostOfRevenue")]))
    assert [r.value for r in rows if r.metric == "cost_of_revenue"] == [150]


def test_ac_26_sga():
    rows = _rows(fixture_s(extra=[seg("x:BetaMember", 60, "us-gaap:SellingGeneralAndAdministrativeExpense")]))
    assert [r.value for r in rows if r.metric == "sga"] == [60]


def test_ac_34_camel_case_split():
    rows = _rows(fixture_s(extra=[seg("x:CloudServicesMember", 5)]))
    assert rows[-1].segment == "Cloud Services" and segment_name("aapl:AmericasSegmentMember") == "Americas"


def test_ac_35_operating_expenses_beats_costs_and_expenses():
    CE = "us-gaap:CostsAndExpenses"
    rows = _rows(fixture_s(extra=[*OPEX, seg("x:AlphaSegmentMember", 110, CE), seg("x:BetaMember", 130, CE)]))
    assert {r.concept for r in rows if r.metric == "opex"} == {"us-gaap:OperatingExpenses"}


def test_ac_36_opex_total_mismatch_is_per_metric():
    rows = _rows(fixture_s(extra=[*OPEX, ("us-gaap:OperatingExpenses", {}, 300, FY25)]))
    assert not any(r.sum_matches_total for r in rows if r.metric == "opex")
    assert all(r.sum_matches_total for r in rows if r.metric == "revenue")


def test_ac_39_operating_segments_member_kept():
    facts = [seg(m, v, extra=OPSEG) for m, v in (("x:AlphaSegmentMember", 300), ("x:BetaMember", 400),
                                                 ("x:GammaSegmentMember", 295))]
    rows = _rows([*facts, (REV, {}, 1000, FY25)])
    assert _vals(rows, "revenue") == _vals(_rows(fixture_s()), "revenue") and len(rows) == 3


def test_duplicate_fact_is_one_row():
    assert len(_rows(fixture_s(extra=[seg("x:AlphaSegmentMember", 300)]))) == 3


def test_zero_total_is_false():
    assert not any(r.sum_matches_total for r in _rows(fixture_s(total=0)))


def test_esef_has_no_opex_metric():
    f = DimFact("us-gaap:OperatingExpenses", 1, "EUR", *FY25, {"ifrs-full:SegmentsAxis": "a:AMember"})
    assert build_segments([f], {}, market="esef", company_id="e", accession=None) == []
