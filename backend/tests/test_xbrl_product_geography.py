from __future__ import annotations

import json

from arp.ingestion.esef import DimFact
from arp.xbrl_pipeline.segments import build_segments
from arp.xbrl_pipeline.store import XbrlStore
from tests.segment_fixture import AXIS, FY25, PROD, REV, fixture_p, ixbrl
from tests.test_xbrl_fetch import CIK10, FakeSource, _annual, _company, _fetch

OPSEG = {"srt:ConsolidationItemsAxis": "us-gaap:OperatingSegmentsMember"}


async def _fetch_p(tmp_path, extra=None):
    store = XbrlStore(tmp_path)
    await _fetch(FakeSource(annual=_annual(content=ixbrl(fixture_p(extra)))), store, company=_company("s1"))
    return store.read_segments(CIK10), json.loads((store.company_dir(CIK10) / "meta.json").read_text())


def _kind(rows, kind):
    return [r for r in rows if r.axis_kind == kind]


def _by_member(rows):
    return {r.member: r for r in rows}


async def test_ac_1_product_rows(tmp_path):
    rows, _ = await _fetch_p(tmp_path)
    assert [r.value for r in _kind(rows, "product")] == [600, 300, 900, 100]


async def test_ac_2_geography_rows(tmp_path):
    rows, _ = await _fetch_p(tmp_path)
    assert [r.value for r in _kind(rows, "geography")] == [400, 350, 250]


async def test_ac_3_segment_rows_unchanged(tmp_path):
    rows, _ = await _fetch_p(tmp_path)
    common = {"company_id": "s1", "market": "sec", "fiscal_year": 2025, "metric": "revenue", "concept": REV,
              "axis": AXIS, "unit": "USD", "period_start": FY25[0], "period_end": FY25[1],
              "sum_matches_total": True, "reconciling": 0, "axis_kind": "segment", "level": None, "form": "10-K"}
    seg = [r.model_dump() for r in _kind(rows, "segment")]
    assert seg == [{**common, "member": m, "segment": s, "value": v, "accession": seg[0]["accession"]}
                   for m, s, v in (("x:AlphaSegmentMember", "Alpha", 300), ("x:BetaMember", "Beta", 400),
                                   ("x:GammaSegmentMember", "Gamma", 295))]


async def test_ac_4_product_levels(tmp_path):
    rows, _ = await _fetch_p(tmp_path)
    levels = {m: r.level for m, r in _by_member(_kind(rows, "product")).items()}
    assert levels == {"x:WidgetsMember": "company", "x:GadgetsMember": "company",
                      "us-gaap:ProductMember": "standard", "us-gaap:ServiceMember": "standard"}


async def test_ac_5_standard_sum_true(tmp_path):
    rows, _ = await _fetch_p(tmp_path)
    std = [r for r in _kind(rows, "product") if r.level == "standard"]
    assert len(std) == 2 and all(r.sum_matches_total for r in std)


async def test_ac_6_company_sum_false(tmp_path):
    rows, _ = await _fetch_p(tmp_path)
    co = [r for r in _kind(rows, "product") if r.level == "company"]
    assert len(co) == 2 and not any(r.sum_matches_total for r in co)


async def test_ac_7_geography_sum_true_level_none(tmp_path):
    rows, _ = await _fetch_p(tmp_path)
    geo = _kind(rows, "geography")
    assert len(geo) == 3 and all(r.sum_matches_total and r.level is None for r in geo)


async def test_ac_8_geography_names(tmp_path):
    rows, _ = await _fetch_p(tmp_path)
    geo = _by_member(_kind(rows, "geography"))
    assert geo["country:US"].segment == "US" and geo["x:RestOfWorldMember"].segment == "Rest Of World"


async def test_ac_9_meta_counts(tmp_path):
    _, meta = await _fetch_p(tmp_path)
    assert (meta["product_count"], meta["geography_count"], meta["segment_count"]) == (4, 3, 3)


async def test_ac_10_segment_by_product_dropped(tmp_path):
    rows, _ = await _fetch_p(tmp_path, [(REV, {AXIS: "x:BetaMember", PROD: "x:WidgetsMember"}, 77, FY25)])
    assert [len(_kind(rows, k)) for k in ("segment", "product", "geography")] == [3, 4, 3]


async def test_ac_11_product_with_operating_pair_kept(tmp_path):
    rows, _ = await _fetch_p(tmp_path, [(REV, {PROD: "x:ToolsMember", **OPSEG}, 50, FY25)])
    assert _by_member(_kind(rows, "product"))["x:ToolsMember"].value == 50


async def test_ac_12_product_revenue_only(tmp_path):
    rows, _ = await _fetch_p(tmp_path, [("us-gaap:CostOfRevenue", {PROD: "x:WidgetsMember"}, 200, FY25)])
    prod = _kind(rows, "product")
    assert prod and {r.metric for r in prod} == {"revenue"}


ESEF_PROD, ESEF_GEO = "ifrs-full:ProductsAndServicesAxis", "ifrs-full:GeographicalAreasAxis"
ESEF_FACTS = [DimFact("ifrs-full:Revenue", v, "EUR", *FY25, {a: m}) for a, m, v in (
    (ESEF_PROD, "ifrs-full:ProductsMember", 70), (ESEF_PROD, "a:ToolsMember", 30),
    (ESEF_GEO, "a:GermanyMember", 60), (ESEF_GEO, "a:EuropeMember", 40))]


def _esef(facts):
    return build_segments(facts, {("ifrs-full:Revenue", 2025): 100}, market="esef", company_id="e1", accession=None)


def test_ac_13_esef_product_geography():
    rows = _esef(ESEF_FACTS)
    assert len(_kind(rows, "product")) == 2 and len(_kind(rows, "geography")) == 2
    assert {r.market for r in rows} == {"esef"}
    assert all(r.level == "standard" for r in rows if r.member.startswith("ifrs-full:"))


def test_ac_19_esef_other_axis_ignored():
    other = DimFact("ifrs-full:Revenue", 5, "EUR", *FY25, {"ifrs-full:ComponentsOfEquityAxis": "a:XMember"})
    rows = _esef([*ESEF_FACTS, other])
    assert len(_kind(rows, "product")) == 2 and len(_kind(rows, "geography")) == 2
