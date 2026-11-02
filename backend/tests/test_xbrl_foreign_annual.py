"""20-F and 40-F filers: the annual report is stored and its segments read (spec xbrl-foreign-annual)."""

from __future__ import annotations

import json

import httpx

from arp.xbrl_pipeline.store import XbrlStore
from tests.segment_fixture import FY25, ixbrl
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
