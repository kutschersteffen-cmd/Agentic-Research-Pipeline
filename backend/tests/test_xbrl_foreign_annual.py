"""20-F and 40-F filers: the annual report is stored and its segments read (spec xbrl-foreign-annual)."""

from __future__ import annotations

import json

import httpx

from arp.xbrl_pipeline.store import XbrlStore
from tests.segment_fixture import FY25, REV, fixture_s, ixbrl, seg
from tests.test_edgar_annual_original import CIK, _client, _source
from tests.test_xbrl_fetch import FakeSource, _company, _fetch

IXBRL_20F = ixbrl([("ifrs-full:Revenue", {}, 1000, FY25)])


class EdgarSource(FakeSource):
    """Company facts from the fake, the annual report through the real EDGAR lookup."""

    def __init__(self, tmp_path, forms, content=IXBRL_20F):
        super().__init__(cik=CIK)
        self.edgar = _source(tmp_path, forms)
        self.content = content

    async def fetch_latest_annual_original(self, cik):
        async with _client(lambda r: httpx.Response(200, content=self.content)) as c:
            return await self.edgar.fetch_latest_annual_original(cik, client=c)


async def _run(tmp_path, forms, content=IXBRL_20F):
    tmp_path.mkdir(exist_ok=True)
    store = XbrlStore(tmp_path / "store")
    st = await _fetch(EdgarSource(tmp_path, forms, content), store, company=_company("f1", cik=None))
    return st, store


async def test_ac_1_20f_stored(tmp_path):
    _, store = await _run(tmp_path, ["6-K", "20-F", "10-Q"])
    meta = store.report_meta(CIK)
    assert (meta.form, meta.accession) == ("20-F", "0000320193-24-000001")


async def test_ac_2_amendment_skipped(tmp_path):
    _, store = await _run(tmp_path, ["20-F/A", "20-F"])
    meta = store.report_meta(CIK)
    assert (meta.form, meta.accession) == ("20-F", "0000320193-24-000001")


async def test_ac_3_40f(tmp_path):
    _, store = await _run(tmp_path, ["40-F"])
    assert store.report_meta(CIK).form == "40-F"


async def test_ac_4_10k_first(tmp_path):
    _, store = await _run(tmp_path, ["10-K", "20-F"])
    assert store.report_meta(CIK).form == "10-K"


async def test_ac_10_no_annual(tmp_path):
    st, store = await _run(tmp_path, ["6-K", "10-Q", "20-F/A"])
    assert store.report_meta(CIK) is None
    meta = json.loads((store.company_dir(CIK) / "meta.json").read_text())
    assert meta["segment_count"] == 0 and st.status == "ok"


IREV, ISEG, IGEO = "ifrs-full:Revenue", "ifrs-full:SegmentsAxis", "ifrs-full:GeographicalAreasAxis"
IFRS_F = [(IREV, {ISEG: "x:AMember"}, 600, FY25), (IREV, {ISEG: "x:BMember"}, 400, FY25), (IREV, {}, 1000, FY25)]
US_F = [seg("x:AlphaSegmentMember", 300), seg("x:BetaMember", 700), (REV, {}, 1000, FY25)]


def _ifrs_note(facts, note):
    return ixbrl([*facts, ("note", note)]).replace(
        b"us-gaap:SegmentReportingDisclosureTextBlock", b"ifrs-full:DisclosureOfOperatingSegmentsExplanatory")


def _segs(store, kind="segment"):
    return [r for r in store.read_segments(CIK) if r.axis_kind == kind]


def _note(store):
    return (store.company_dir(CIK) / "segment_note.txt").read_text().strip()


async def test_ac_5_ifrs_segments(tmp_path):
    _, store = await _run(tmp_path, ["20-F"], ixbrl(IFRS_F))
    rows = _segs(store)
    assert [r.value for r in rows] == [600, 400]
    assert {(r.market, r.form, r.sum_matches_total) for r in rows} == {("sec", "20-F", True)}


async def test_ac_6_ifrs_geography(tmp_path):
    _, base = await _run(tmp_path / "a", ["20-F"], ixbrl(IFRS_F))
    geo = [(IREV, {IGEO: "x:EuropeMember"}, 700, FY25), (IREV, {IGEO: "x:AsiaMember"}, 300, FY25)]
    _, store = await _run(tmp_path / "b", ["20-F"], ixbrl([*IFRS_F, *geo]))
    assert [r.value for r in _segs(store, "geography")] == [700, 300]
    assert _segs(store) == _segs(base)


async def test_ac_7_ifrs_note(tmp_path):
    _, store = await _run(tmp_path, ["20-F"], _ifrs_note(IFRS_F, "Segment A sells ore."))
    assert _note(store) == "Segment A sells ore."


async def test_ac_8_us_gaap_20f(tmp_path):
    _, store = await _run(tmp_path, ["20-F"], ixbrl(US_F))
    rows = _segs(store)
    assert len(rows) == 2 and all(r.form == "20-F" and r.concept.startswith("us-gaap:") for r in rows)


async def test_ac_12_us_gaap_note(tmp_path):
    _, store = await _run(tmp_path, ["20-F"], ixbrl([*US_F, ("note", "Two segments.")]))
    assert _note(store) == "Two segments."


async def test_ac_13_tie_break_more_rows(tmp_path):
    _, store = await _run(tmp_path, ["20-F"], ixbrl([*US_F, (IREV, {ISEG: "x:AMember"}, 600, FY25)]))
    rows = _segs(store)
    assert len(rows) == 2 and all(r.concept.startswith("us-gaap:") for r in rows)


async def test_ac_9_fixture_s_10k(tmp_path):
    _, store = await _run(tmp_path, ["10-K"], ixbrl(fixture_s()))
    assert [(r.member, r.value, r.form) for r in _segs(store)] == [
        ("x:AlphaSegmentMember", 300, "10-K"), ("x:BetaMember", 400, "10-K"), ("x:GammaSegmentMember", 295, "10-K")]


def test_ac_11_rows_stored_before_form_still_read(tmp_path):
    # the existing XBRL/ESEF/segment files are AC-11's real check; this pins the default that keeps them readable
    store = XbrlStore(tmp_path)
    store.company_dir(CIK).mkdir(parents=True)
    old = {"company_id": "s1", "market": "esef", "fiscal_year": 2025, "metric": "revenue", "concept": IREV,
           "axis": ISEG, "member": "x:AMember", "segment": "A", "value": 600, "unit": "EUR", "period_start": None,
           "period_end": "2025-12-31", "accession": None, "sum_matches_total": True}
    (store.company_dir(CIK) / "segments.jsonl").write_text(json.dumps(old) + "\n")
    assert store.read_segments(CIK)[0].form is None
