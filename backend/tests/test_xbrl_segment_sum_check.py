from __future__ import annotations

import json

from arp.xbrl_pipeline.store import XbrlStore
from tests.segment_fixture import FY24, FY25, Q4, fixture_p, ixbrl, seg
from tests.test_xbrl_fetch import CIK10, FakeSource, _annual, _company, _fetch

REVS = "us-gaap:Revenues"
OPEX = "us-gaap:OperatingExpenses"
CI = "srt:ConsolidationItemsAxis"
CORP = "us-gaap:CorporateNonSegmentMember"
ELIM = "us-gaap:ConsolidationEliminationsMember"


def ci(member, value, concept=REVS, period=FY25, extra=None):
    return (concept, {CI: member, **(extra or {})}, value, period)


def fixture_k(total=47941, corp=(CORP, 144), elim=(ELIM, -1009), extra=()):
    segs = [seg(f"x:{n}Member", v, REVS) for n, v in
            (("A", 19586), ("B", 11513), ("C", 6334), ("D", 5638), ("E", 5735))]
    rec = [ci(m, v) for m, v in (corp, elim) if m]
    return [*segs, (REVS, {}, total, FY25), *rec, *extra]


def simple(members, total, concept=REVS, extra=()):
    facts = [seg(m, v, concept) for m, v in members]
    return facts + ([(concept, {}, total, FY25)] if total is not None else []) + list(extra)


async def _run(tmp_path, facts):
    store = XbrlStore(tmp_path)
    await _fetch(FakeSource(annual=_annual(content=ixbrl(facts))), store, company=_company("s1"))
    meta = json.loads((store.company_dir(CIK10) / "meta.json").read_text())
    return store.read_segments(CIK10), meta


def _seg(rows, metric="revenue"):
    return [r for r in rows if r.axis_kind == "segment" and r.metric == metric]


def _all(rows, match, rec):
    return rows and all(r.sum_matches_total is match and r.reconciling == rec for r in rows)


async def test_ac_1_fixture_k(tmp_path):
    rows = _seg((await _run(tmp_path, fixture_k()))[0])
    assert len(rows) == 5 and _all(rows, True, -865)


async def test_ac_2_positive_elimination(tmp_path):
    rows = _seg((await _run(tmp_path, fixture_k(elim=(ELIM, 1009))))[0])
    assert _all(rows, True, -865)


async def test_ac_3_intersegment_elimination(tmp_path):
    rows = _seg((await _run(tmp_path, fixture_k(elim=("srt:IntersegmentEliminationMember", -1009))))[0])
    assert rows and all(r.sum_matches_total for r in rows)


async def test_ac_4_no_reconciling(tmp_path):
    rows = _seg((await _run(tmp_path, fixture_k(corp=(None, 0), elim=(None, 0))))[0])
    assert _all(rows, False, 0)


async def test_ac_5_corporate_with_segment_member(tmp_path):
    extra = [ci(CORP, 500, extra={"us-gaap:StatementBusinessSegmentsAxis": "x:AMember"})]
    rows = _seg((await _run(tmp_path, fixture_k(extra=extra)))[0])
    assert {r.reconciling for r in rows} == {-865}


async def test_ac_6_prior_year_corporate(tmp_path):
    rows = _seg((await _run(tmp_path, fixture_k(extra=[ci(CORP, 500, period=FY24)])))[0])
    assert {r.reconciling for r in rows} == {-865}


async def test_ac_7_total_member_dropped(tmp_path):
    rows, meta = await _run(tmp_path, simple(
        [("x:XMember", 53000), ("x:YMember", 8000), ("x:TotalSegmentMember", 61000)], 61000))
    rows = _seg(rows)
    assert [r.member for r in rows] == ["x:XMember", "x:YMember"] and all(r.sum_matches_total for r in rows)
    assert meta["segment_count"] == 2


async def test_ac_8_duplicate_member(tmp_path):
    rows = _seg((await _run(tmp_path, simple([("x:PMember", 5169784), ("x:QMember", 5169784)], 5169784)))[0])
    assert [(r.value, r.sum_matches_total) for r in rows] == [(5169784, True)]


async def test_ac_9_total_member_dropped_whatever_total(tmp_path):
    rows = _seg((await _run(tmp_path, simple([("x:XMember", 60), ("x:YMember", 40), ("x:ZMember", 100)], 200)))[0])
    assert [(r.member, r.sum_matches_total) for r in rows] == [("x:XMember", False), ("x:YMember", False)]


async def test_ac_10_total_member_matches(tmp_path):
    rows = _seg((await _run(tmp_path, simple([("x:XMember", 60), ("x:YMember", 40), ("x:ZMember", 100)], 100)))[0])
    assert [(r.member, r.sum_matches_total) for r in rows] == [("x:XMember", True), ("x:YMember", True)]


async def test_ac_11_lone_corporate_and_other(tmp_path):
    rows, meta = await _run(tmp_path, simple([("us-gaap:CorporateAndOtherMember", -26885000)], 1000))
    assert _seg(rows) == [] and meta["segment_count"] == 0


async def test_ac_12_lone_all_other_segments_20f(tmp_path):
    rev = "ifrs-full:Revenue"
    facts = [(rev, {"ifrs-full:SegmentsAxis": "ifrs-full:AllOtherSegmentsMember"}, 0, FY25), (rev, {}, 1000, FY25)]
    rows, _ = await _run(tmp_path, facts)
    assert _seg(rows) == []


async def test_ac_13_corporate_with_other_kept(tmp_path):
    rows = _seg((await _run(tmp_path, simple([("us-gaap:CorporateMember", 10), ("x:RetailMember", 90)], 100)))[0])
    assert [r.member for r in rows] == ["us-gaap:CorporateMember", "x:RetailMember"]


async def test_ac_14_product_geography_unchanged(tmp_path):
    rows, _ = await _run(tmp_path, fixture_p())
    prod = [r for r in rows if r.axis_kind == "product"]
    geo = [r for r in rows if r.axis_kind == "geography"]
    assert [r.value for r in prod] == [600, 300, 900, 100]
    assert [r.value for r in geo] == [400, 350, 250]
    assert {r.reconciling for r in prod + geo} == {None}


async def test_ac_16_opex(tmp_path):
    facts = simple([("x:AMember", 100), ("x:BMember", 50)], 120, OPEX, extra=[ci(CORP, -30, OPEX)])
    rows = _seg((await _run(tmp_path, facts))[0], "opex")
    assert len(rows) == 2 and _all(rows, True, -30)


async def test_ac_17_srt_corporate(tmp_path):
    rows = _seg((await _run(tmp_path, fixture_k(corp=("srt:CorporateNonSegmentMember", 144))))[0])
    assert {r.reconciling for r in rows} == {-865}


async def test_ac_18_segment_reconciling_items(tmp_path):
    rows = _seg((await _run(tmp_path, fixture_k(total=47951, extra=[ci("us-gaap:SegmentReconcilingItemsMember", 10)])))[0])
    assert _all(rows, True, -855)


async def test_ac_19_company_prefix_ignored(tmp_path):
    rows = _seg((await _run(tmp_path, fixture_k(extra=[ci("x:CorporateNonSegmentMember", 500)])))[0])
    assert {r.reconciling for r in rows} == {-865}


async def test_ac_20_quarter_ignored(tmp_path):
    rows = _seg((await _run(tmp_path, fixture_k(extra=[ci(CORP, 50, period=Q4)])))[0])
    assert {r.reconciling for r in rows} == {-865}


async def test_ac_21_one_percent_off(tmp_path):
    rows = _seg((await _run(tmp_path, simple([("x:AMember", 990)], 1000)))[0])
    assert [r.sum_matches_total for r in rows] == [True]


async def test_ac_22_over_one_percent_off(tmp_path):
    rows = _seg((await _run(tmp_path, simple([("x:AMember", 989)], 1000)))[0])
    assert [r.sum_matches_total for r in rows] == [False]


async def test_ac_23_total_within_half_percent(tmp_path):
    rows = _seg((await _run(tmp_path, simple([("x:XMember", 600), ("x:YMember", 400), ("x:ZMember", 1005)], 1000)))[0])
    assert len(rows) == 2


async def test_ac_24_total_over_half_percent(tmp_path):
    rows = _seg((await _run(tmp_path, simple([("x:XMember", 600), ("x:YMember", 400), ("x:ZMember", 1006)], 1000)))[0])
    assert len(rows) == 3


async def test_ac_25_lone_corporate_non_segment(tmp_path):
    rows, meta = await _run(tmp_path, simple([("srt:CorporateNonSegmentMember", 5)], 1000))
    assert _seg(rows) == [] and meta["segment_count"] == 0


async def test_ac_26_zero_total(tmp_path):
    rows = _seg((await _run(tmp_path, simple([("x:AMember", 10), ("x:BMember", 20)], 0)))[0])
    assert len(rows) == 2 and not any(r.sum_matches_total for r in rows)
