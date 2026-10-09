from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from arp.config import Settings
from arp.ingestion.edgar import AnnualOriginal
from arp.schemas.common import CompanyRef
from arp.storage.run_store import RunStore
from arp.xbrl_pipeline.fetch import (
    FETCH_DELAY_SECONDS,
    create_xbrl_run,
    execute_xbrl_run,
    fetch_company,
    with_retry,
)
from arp.xbrl_pipeline.store import XbrlStore

FIXTURE = Path(__file__).parent / "fixtures" / "xbrl" / "companyfacts_small.json"
CIK10 = "0001234567"
INLINE = b'<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">x</html>'


async def _nosleep(_: float) -> None:
    return None


def _annual(accession: str = "0001-23-000001", content: bytes = INLINE) -> AnnualOriginal:
    return AnnualOriginal(
        accession=accession, form="10-K", filing_date="2024-02-01",
        source_url="https://sec.example/x", primary_document="x.htm", content=content,
    )


class FakeSource:
    def __init__(self, *, facts="fixture", annual="default", annual_exc=None, facts_exc=None, cik="1234567") -> None:
        self.raw = FIXTURE.read_bytes()
        self.facts = json.loads(self.raw) if facts == "fixture" else facts
        self.annual = _annual() if annual == "default" else annual
        self.annual_exc, self.facts_exc, self.cik = annual_exc, facts_exc, cik
        self.calls: list[str] = []

    async def resolve_cik(self, cik, ticker):
        return cik or self.cik

    async def fetch_company_facts_raw(self, cik):
        self.calls.append("facts")
        if self.facts_exc:
            raise self.facts_exc
        return (self.facts, self.raw if self.facts is not None else None)

    async def fetch_latest_annual_original(self, cik):
        self.calls.append("annual")
        if self.annual_exc:
            raise self.annual_exc
        return self.annual


def _company(cid="ACME", cik: str | None = "1234567") -> CompanyRef:
    return CompanyRef(company_id=cid, name=cid, cik=cik)


async def _fetch(source, store, tags=None, company=None):
    return await fetch_company(company or _company(), source=source, store=store, tags=tags, sleep=_nosleep)


def _status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://x")
    return httpx.HTTPStatusError("e", request=req, response=httpx.Response(code, request=req))


async def test_fetch_ok_writes_everything(tmp_path):
    store = XbrlStore(tmp_path)
    st = await _fetch(FakeSource(), store)
    assert (st.status, st.fact_count, st.report, st.cik) == ("ok", 5, "stored", CIK10)
    assert len(list(store.read_facts(CIK10))) == 5
    assert len(store.read_catalog(CIK10)) == 3
    concepts = {r.concept for r in store.read_required(CIK10)}
    assert {"us-gaap:Revenues", "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"} <= concepts
    assert store.meta(CIK10)["source_sha"] == st.source_sha
    assert store.report_meta(CIK10).inline_xbrl is True


async def test_second_fetch_is_unchanged_including_report(tmp_path):
    store, src = XbrlStore(tmp_path), FakeSource()
    await _fetch(src, store)
    st = await _fetch(src, store)
    assert (st.status, st.report) == ("unchanged", "unchanged")


async def test_tags_filter_writes_subset_but_keeps_original_and_required(tmp_path):
    store = XbrlStore(tmp_path)
    st = await _fetch(FakeSource(), store, tags=frozenset({"us-gaap:Revenues"}))
    assert st.status == "ok" and st.report == "stored"
    assert len(list(store.read_facts(CIK10))) == 3
    assert store.original(CIK10) is not None
    assert store.read_required(CIK10)


async def test_tags_matching_nothing_is_ok_with_empty_facts(tmp_path):
    store = XbrlStore(tmp_path)
    st = await _fetch(FakeSource(), store, tags=frozenset({"us-gaap:Nope"}))
    assert (st.status, st.fact_count) == ("ok", 0)
    assert list(store.read_facts(CIK10)) == []
    assert store.original(CIK10) is not None
    assert store.read_required(CIK10)


async def test_changed_tag_set_is_not_unchanged(tmp_path):
    store, src = XbrlStore(tmp_path), FakeSource()
    await _fetch(src, store, tags=frozenset({"us-gaap:Revenues"}))
    st = await _fetch(src, store, tags=None)
    assert st.status == "ok" and st.fact_count == 5


async def test_404_is_not_found(tmp_path):
    st = await _fetch(FakeSource(facts=None), XbrlStore(tmp_path))
    assert st.status == "not_found"


async def test_no_cik(tmp_path):
    st = await _fetch(FakeSource(cik=None), XbrlStore(tmp_path), company=_company(cik=None))
    assert (st.status, st.cik) == ("no_cik", None)


async def test_same_cik_twice_stores_one_original_and_one_report(tmp_path):
    store, src = XbrlStore(tmp_path), FakeSource()
    await _fetch(src, store, company=_company("A"))
    st_b = await _fetch(src, store, company=_company("B"))
    assert (st_b.status, st_b.report) == ("unchanged", "unchanged")
    d = store.company_dir(CIK10)
    assert len(list(d.glob("companyfacts-*.json"))) == 1
    assert len(list(d.glob("annual-*.htm"))) == 1


async def test_unchanged_refetch_under_new_company_id_only_records_the_id(tmp_path):
    store, src = XbrlStore(tmp_path), FakeSource()
    await _fetch(src, store, company=_company("acme"))
    facts = store.company_dir(CIK10) / "facts.jsonl"
    before = (facts.read_bytes(), facts.stat().st_mtime_ns)
    st = await _fetch(src, store, company=_company("acme-inc"))
    assert st.status == "unchanged"
    assert store.company_ids(CIK10) == ["acme", "acme-inc"]
    assert (facts.read_bytes(), facts.stat().st_mtime_ns) == before
    assert {r.company_id for r in store.read_required(CIK10)} == {"acme"}


async def test_non_numeric_cik_is_no_cik(tmp_path):
    st = await _fetch(FakeSource(cik="../x"), XbrlStore(tmp_path), company=_company(cik=None))
    assert (st.status, st.cik) == ("no_cik", None)


async def test_report_failure_is_logged(tmp_path, caplog):
    st = await _fetch(FakeSource(annual_exc=ValueError("boom")), XbrlStore(tmp_path))
    assert st.report == "error"
    assert f"annual report for {CIK10} not stored: boom" in caplog.text


async def test_report_not_inline_is_stored_and_flagged(tmp_path):
    store = XbrlStore(tmp_path)
    st = await _fetch(FakeSource(annual=_annual(content=b"<html>plain</html>")), store)
    assert st.report == "stored" and store.report_meta(CIK10).inline_xbrl is False


async def test_no_10k_gives_report_none_and_company_ok(tmp_path):
    st = await _fetch(FakeSource(annual=None), XbrlStore(tmp_path))
    assert (st.status, st.report) == ("ok", "none")


async def test_report_download_failure_leaves_company_ok(tmp_path):
    store = XbrlStore(tmp_path)
    st = await _fetch(FakeSource(annual_exc=RuntimeError("boom")), store)
    assert (st.status, st.report) == ("ok", "error")
    assert st.fact_count == 5 and len(list(store.read_facts(CIK10))) == 5 and store.meta(CIK10)


async def test_with_retry_succeeds_after_two_429():
    n = 0

    async def call():
        nonlocal n
        n += 1
        if n < 3:
            raise _status_error(429)
        return "ok"

    assert await with_retry(call, sleep=_nosleep) == "ok" and n == 3


async def test_with_retry_gives_up_after_three_and_404_is_not_retried():
    n = 0

    async def always_503():
        nonlocal n
        n += 1
        raise _status_error(503)

    with pytest.raises(httpx.HTTPStatusError):
        await with_retry(always_503, sleep=_nosleep)
    assert n == 3
    n = 0

    async def nf():
        nonlocal n
        n += 1
        raise _status_error(404)

    with pytest.raises(httpx.HTTPStatusError):
        await with_retry(nf, sleep=_nosleep)
    assert n == 1


def test_delay_constant():
    assert FETCH_DELAY_SECONDS == 0.15


async def test_run_isolates_a_failing_company_and_resume_retries_it(tmp_path):
    settings = Settings(xbrl_dir=tmp_path / "xbrl")
    run_store = RunStore(tmp_path / "runs")
    companies = [_company("A", "1"), _company("B", "2"), _company("C", "3")]

    class Flaky(FakeSource):
        broken = True

        async def fetch_company_facts_raw(self, cik):
            if cik == "2" and self.broken:
                raise ValueError("bad")
            return await super().fetch_company_facts_raw(cik)

    src = Flaky()
    run_id = create_xbrl_run(companies, None, False, run_store)
    await execute_xbrl_run(run_id, companies, settings=settings, run_store=run_store, tags=None, refresh=False, source=src)

    def lines(p):
        return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]

    assert len(lines(run_store.errors_path(run_id))) == 1
    assert {r["company_id"] for r in lines(run_store.results_path(run_id))} == {"A", "C"}

    src.broken = False
    await execute_xbrl_run(run_id, companies, settings=settings, run_store=run_store, tags=None, refresh=False, source=src)
    assert {r["company_id"] for r in lines(run_store.results_path(run_id))} == {"A", "B", "C"}


class _Flaky(FakeSource):
    """Company "2" fails while `broken`; records the manifest status seen on every call."""

    def __init__(self, run_store, run_id) -> None:
        super().__init__()
        self.broken, self.seen, self._rs, self._id = True, [], run_store, run_id

    async def fetch_company_facts_raw(self, cik):
        self.seen.append(self._rs.load_manifest(self._id).status)
        if cik == "2" and self.broken:
            raise ValueError("bad")
        return await super().fetch_company_facts_raw(cik)


async def _first_run_with_failure(tmp_path):
    settings = Settings(xbrl_dir=tmp_path / "xbrl")
    run_store = RunStore(tmp_path / "runs")
    companies = [_company("A", "1"), _company("B", "2"), _company("C", "3")]
    run_id = create_xbrl_run(companies, None, False, run_store)
    src = _Flaky(run_store, run_id)

    async def run():
        await execute_xbrl_run(run_id, companies, settings=settings, run_store=run_store, tags=None, refresh=False, source=src)
        return run_store.load_manifest(run_id)

    m = await run()
    assert (m.completed_count, m.failed_count, m.status) == (2, 1, "partially_completed")
    return run, src


async def test_resume_recomputes_counts_and_runs_as_running(tmp_path):
    run, src = await _first_run_with_failure(tmp_path)
    src.broken, src.seen = False, []
    m = await run()
    assert (m.completed_count, m.failed_count, m.status) == (3, 0, "completed")
    assert src.seen == ["running"]  # only B is retried, and the run was RUNNING meanwhile


async def test_resume_with_persisting_failure_does_not_double_count(tmp_path):
    run, _ = await _first_run_with_failure(tmp_path)
    m = await run()
    assert (m.completed_count, m.failed_count, m.status) == (2, 1, "partially_completed")


async def test_execute_run_dispatches_esef(tmp_path):
    from tests.test_xbrl_esef_fetch import FakeSource as EsefFake  # noqa: PLC0415

    settings = Settings(xbrl_dir=tmp_path / "xbrl")
    run_store = RunStore(tmp_path / "runs")
    companies = [CompanyRef(company_id="A", name="A", lei="529900FIXTURELEI0001"), CompanyRef(company_id="B", name="B")]
    run_id = create_xbrl_run(companies, None, False, run_store, market="esef")
    assert run_store.load_manifest(run_id).params["market"] == "esef"
    await execute_xbrl_run(run_id, companies, settings=settings, run_store=run_store, tags=None, refresh=False,
                           market="esef", source=EsefFake())
    rows = {r["company_id"]: r for r in map(json.loads, run_store.results_path(run_id).read_text().splitlines())}
    assert (rows["A"]["status"], rows["B"]["status"]) == ("ok", "no_lei")


@pytest.mark.parametrize("accession", ["../../evil", "0001-23\\x"])
async def test_unsafe_accession_gives_report_error_and_writes_nothing(tmp_path, accession):
    store = XbrlStore(tmp_path)
    st = await _fetch(FakeSource(annual=_annual(accession=accession)), store)
    assert (st.status, st.report) == ("ok", "error")
    assert store.report_meta(CIK10) is None
    assert not list(tmp_path.rglob("annual-*")) and not list(tmp_path.parent.glob("evil*"))
