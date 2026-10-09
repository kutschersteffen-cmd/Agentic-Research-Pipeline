from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx
import pytest

from arp.schemas.common import CompanyRef
from arp.xbrl_pipeline.fetch_esef import (
    EsefFiling,
    IndexEsefSource,
    fetch_company_esef,
    normalise_lei,
    pick_latest,
)
from arp.xbrl_pipeline.store import XbrlStore

JSON_BYTES = (Path(__file__).parent / "fixtures" / "xbrl_esef_sample.json").read_bytes()
LEI = "529900FIXTURELEI0001"
ATTRS = {
    "id": "1", "fxo_id": f"{LEI}-2022-12-31-ESEF-DE-0", "date_added": "2023-04-01 10:00:00.000000",
    "period_end": "2022-12-31", "json_url": "/x.json", "package_url": "/x.zip", "report_url": "/a/reports/x.xhtml",
}


def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("reports/x.xhtml", "<html/>")
    return buf.getvalue()


class FakeSource:
    def __init__(self, filing="default") -> None:
        self.filing = EsefFiling(ATTRS, JSON_BYTES, _zip(), "https://idx.example/x.zip") if filing == "default" else filing
        self.asked: list[str] = []

    async def latest_filing(self, lei, known_accession=None):
        self.asked.append(lei)
        return self.filing


async def _nosleep(_):
    return None


def _co(cid="c1", lei=LEI):
    return CompanyRef(company_id=cid, name=cid, lei=lei)


async def _run(src, store, tags=None, company=None):
    return await fetch_company_esef(company or _co(), source=src, store=store, tags=tags, sleep=_nosleep)


async def test_ok_stores_json_zip_facts_required_and_meta(tmp_path):
    store = XbrlStore(tmp_path)
    st = await _run(FakeSource(), store)
    assert (st.status, st.cik, st.report, st.market) == ("ok", LEI, "stored", "esef")
    d = store.company_dir(LEI)
    assert len(list(d.glob("xbrl-json-*.json"))) == 1 and len(list(d.glob("package-*.zip"))) == 1
    meta = store.meta(LEI)
    assert meta["market"] == "esef" and meta["original_file"].startswith("xbrl-json-")
    assert meta["filing"] == {"fxo_id": ATTRS["fxo_id"], "date_added": ATTRS["date_added"]}
    rows = list(store.read_facts(LEI))
    assert rows and {r.market for r in rows} == {"esef"}
    assert any(r.metric == "revenue" and r.status == "found" for r in store.read_required(LEI))
    rep = store.report_meta(LEI)
    assert (rep.form, rep.accession, rep.filing_date, rep.primary_document, rep.inline_xbrl) == (
        "ESEF", ATTRS["fxo_id"], "2023-04-01", "x.xhtml", True)


async def test_second_run_is_unchanged(tmp_path):
    store = XbrlStore(tmp_path)
    await _run(FakeSource(), store)
    st = await _run(FakeSource(), store)
    assert (st.status, st.report) == ("unchanged", "unchanged")


async def test_tag_selection_filters_facts_but_not_required(tmp_path):
    store = XbrlStore(tmp_path)
    await _run(FakeSource(), store, tags=frozenset({"ifrs-full:Equity"}))
    assert {r.concept for r in store.read_facts(LEI)} == {"Equity"}
    assert any(r.metric == "revenue" and r.status == "found" for r in store.read_required(LEI))
    st = await _run(FakeSource(), store, tags=None)
    assert st.status == "ok"


async def test_lowercase_and_spaced_lei_is_normalised(tmp_path):
    store = XbrlStore(tmp_path)
    src = FakeSource()
    st = await _run(src, store, company=_co(lei=f" {LEI.lower()} "))
    assert st.cik == LEI and src.asked == [LEI]


@pytest.mark.parametrize("lei", ["short", "../../etc/passwd", None])
async def test_invalid_lei_is_no_lei_and_writes_nothing(tmp_path, lei):
    st = await _run(FakeSource(), XbrlStore(tmp_path), company=_co(lei=lei))
    assert (st.status, st.cik) == ("no_lei", None)
    assert list(tmp_path.iterdir()) == []


async def test_no_filing_is_not_found(tmp_path):
    st = await _run(FakeSource(filing=None), XbrlStore(tmp_path))
    assert (st.status, st.cik) == ("not_found", LEI)


async def test_same_lei_two_company_ids_merge(tmp_path):
    store = XbrlStore(tmp_path)
    await _run(FakeSource(), store, company=_co("c1"))
    st = await _run(FakeSource(), store, company=_co("c2"))
    assert st.status == "unchanged" and store.company_ids(LEI) == ["c1", "c2"]


async def test_empty_package_gives_report_none_and_keeps_status_ok(tmp_path):
    store = XbrlStore(tmp_path)
    st = await _run(FakeSource(EsefFiling(ATTRS, JSON_BYTES, b"", "https://idx.example/x.zip")), store)
    assert (st.status, st.report) == ("ok", "none")
    assert list(store.read_facts(LEI))


def test_normalise_lei():
    assert normalise_lei(" abcdefghij0123456789 ") == "ABCDEFGHIJ0123456789"
    assert normalise_lei("abc") is None and normalise_lei(None) is None


def _f(period_end, **kw):
    return {"period_end": period_end, "json_url": "/j", "package_url": "/p", **kw}


def test_pick_latest_ignores_bogus_years():
    got = pick_latest([_f("4172-12-31"), _f("1900-12-31"), _f("2023-12-31")], this_year=2026)
    assert got["period_end"] == "2023-12-31"


def test_pick_latest_skips_filings_without_json_url():
    got = pick_latest([{"period_end": "2024-12-31", "package_url": "/p"}, _f("2023-12-31")], this_year=2026)
    assert got["period_end"] == "2023-12-31"
    assert pick_latest([], this_year=2026) is None


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_index_source_downloads_both_files():
    def handler(req):
        p = req.url.path
        if p.endswith("/filings"):
            return httpx.Response(200, json={"data": [{"id": "1", "attributes": {
                "fxo_id": "f", "date_added": "2023-01-01 00:00:00", "period_end": "2022-12-31",
                "json_url": "/a/x.json", "package_url": "/a/x.zip"}}]})
        return httpx.Response(200, content=b"J" if p.endswith(".json") else b"Z")

    src = IndexEsefSource("https://8.8.8.8/idx", client=_client(handler))
    f = await src.latest_filing(LEI)
    assert (f.facts_json, f.package, f.package_url) == (b"J", b"Z", "https://8.8.8.8/a/x.zip")


async def test_index_source_404_is_none():
    src = IndexEsefSource("https://8.8.8.8", client=_client(lambda r: httpx.Response(404)))
    assert await src.latest_filing(LEI) is None


def test_pick_latest_ignores_malformed_period_end():
    got = pick_latest([_f("n/a"), _f(None), _f("2023-12-31")], this_year=2026)
    assert got["period_end"] == "2023-12-31"


@pytest.mark.parametrize("package", [httpx.Response(404), httpx.Response(200, content=b"Z" * (len(JSON_BYTES) + 100))])
async def test_package_failure_keeps_company_ok_with_report_error(tmp_path, package):
    def handler(req):
        p = req.url.path
        if p.endswith("/filings"):
            return httpx.Response(200, json={"data": [{"id": "1", "attributes": {
                "fxo_id": ATTRS["fxo_id"], "date_added": ATTRS["date_added"], "period_end": "2022-12-31",
                "json_url": "/a/x.json", "package_url": "/a/x.zip"}}]})
        return httpx.Response(200, content=JSON_BYTES) if p.endswith(".json") else package

    src = IndexEsefSource("https://8.8.8.8", client=_client(handler), max_bytes=len(JSON_BYTES) + 10)
    store = XbrlStore(tmp_path)
    st = await _run(src, store)
    assert (st.status, st.report) == ("ok", "error")
    assert list(store.read_facts(LEI)) and store.report_meta(LEI) is None


def test_pick_latest_breaks_period_ties_on_date_added_then_fxo_id():
    a, b = _f("2023-12-31", date_added="2024-03-01", fxo_id="a"), _f("2023-12-31", date_added="2024-05-01", fxo_id="b")
    assert pick_latest([b, a], this_year=2026) is b and pick_latest([a, b], this_year=2026) is b
    c, d = _f("2023-12-31", date_added="2024-05-01", fxo_id="c"), _f("2023-12-31", date_added="2024-05-01", fxo_id="d")
    assert pick_latest([d, c], this_year=2026) is d and pick_latest([c, d], this_year=2026) is d


def _index_handler(package, seen=None):
    def handler(req):
        p = req.url.path
        if seen is not None:
            seen.append(p)
        if p.endswith("/filings"):
            return httpx.Response(200, json={"data": [{"id": "1", "attributes": {
                "fxo_id": ATTRS["fxo_id"], "date_added": ATTRS["date_added"], "period_end": "2022-12-31",
                "json_url": "/a/x.json", "package_url": "/a/x.zip"}}]})
        return httpx.Response(200, content=JSON_BYTES) if p.endswith(".json") else package
    return handler


async def test_package_that_is_not_a_zip_is_report_error(tmp_path):
    src = IndexEsefSource("https://8.8.8.8", client=_client(_index_handler(
        httpx.Response(200, content=b"<html>Service unavailable</html>"))))
    store = XbrlStore(tmp_path)
    st = await _run(src, store)
    assert (st.status, st.report) == ("ok", "error")
    assert store.report_meta(LEI) is None and not list(store.company_dir(LEI).glob("package-*"))


async def test_unchanged_package_is_not_downloaded_again(tmp_path):
    seen: list[str] = []
    src = IndexEsefSource("https://8.8.8.8", client=_client(_index_handler(httpx.Response(200, content=_zip()), seen)))
    store = XbrlStore(tmp_path)
    assert (await _run(src, store)).report == "stored"
    seen.clear()
    st = await _run(src, store)
    assert (st.status, st.report) == ("unchanged", "unchanged")
    assert not [p for p in seen if p.endswith(".zip")]
