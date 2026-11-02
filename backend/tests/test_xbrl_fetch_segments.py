from __future__ import annotations

import json

from arp.xbrl_pipeline.store import XbrlStore
from tests.segment_fixture import FY25, NOTE, REV, fixture_s, ixbrl, seg
from tests.test_xbrl_fetch import CIK10, FakeSource, _annual, _company, _fetch


async def _run(tmp_path, content: bytes, monkeypatch=None):
    store = XbrlStore(tmp_path)
    st = await _fetch(FakeSource(annual=_annual(content=content)), store, company=_company("s1"))
    return st, store


def _meta(store):
    return json.loads((store.company_dir(CIK10) / "meta.json").read_text())


async def test_ac_1_and_ac_2_fixture_s(tmp_path):
    st, store = await _run(tmp_path, ixbrl(fixture_s()))
    rows = store.read_segments(CIK10)
    assert [(r.member, r.value) for r in rows] == [
        ("x:AlphaSegmentMember", 300), ("x:BetaMember", 400), ("x:GammaSegmentMember", 295)]
    assert {(r.unit, r.fiscal_year, r.market, r.company_id) for r in rows} == {("USD", 2025, "sec", "s1")}
    assert _meta(store)["segment_count"] == 3 and st.status == "ok"


async def test_ac_14_ac_15_ac_16_not_ixbrl(tmp_path):
    st, store = await _run(tmp_path, b"<html><body>plain 10-K</body></html>")
    assert store.report_meta(CIK10).inline_xbrl is False
    assert (store.company_dir(CIK10) / "segments.jsonl").read_text() == ""
    assert _meta(store)["segment_count"] == 0
    assert st.status == "ok"


async def test_ac_17_member_without_dimension(tmp_path):
    st, store = await _run(tmp_path, ixbrl(fixture_s(extra=[(REV, {None: "x:DeltaMember"}, 5, FY25)])))
    assert st.status == "ok" and len(store.read_segments(CIK10)) == 3


async def test_ac_27_count_across_metrics(tmp_path):
    PP = "us-gaap:PaymentsToAcquireProductiveAssets"
    _, store = await _run(tmp_path, ixbrl(fixture_s(extra=[seg("x:AlphaSegmentMember", 50, PP), seg("x:BetaMember", 70, PP)])))
    assert _meta(store)["segment_count"] == 5


async def test_ac_29_note_written(tmp_path):
    _, store = await _run(tmp_path, ixbrl(fixture_s(note=NOTE)))
    assert (store.company_dir(CIK10) / "segment_note.txt").read_text() == NOTE
    assert _meta(store)["segment_note_chars"] == 40


async def test_ac_30_no_note(tmp_path):
    _, store = await _run(tmp_path, ixbrl(fixture_s()))
    assert not (store.company_dir(CIK10) / "segment_note.txt").exists()
    assert _meta(store)["segment_note_chars"] == 0


async def test_segment_failure_keeps_status(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr("arp.xbrl_pipeline.fetch.write_segments_sec", boom)
    st, _ = await _run(tmp_path, ixbrl(fixture_s()))
    assert st.status == "ok" and st.report == "stored"


async def test_refetch_unchanged_keeps_segments(tmp_path):
    store = XbrlStore(tmp_path)
    src = FakeSource(annual=_annual(content=ixbrl(fixture_s())))
    await _fetch(src, store, company=_company("s1"))
    st = await _fetch(src, store, company=_company("s1"))
    assert (st.status, st.report) == ("unchanged", "unchanged") and len(store.read_segments(CIK10)) == 3
