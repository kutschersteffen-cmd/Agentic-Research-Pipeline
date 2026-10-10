from __future__ import annotations

import json

import pytest

from arp.config import Settings
from arp.schemas.common import CompanyRef
from arp.schemas.issuer import IdentifierMap
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.run_store import RunStore
from arp.universe_workbench.mapping import MasterIndex
from arp.xbrl_pipeline.fetch import create_xbrl_run, execute_xbrl_run, load_routing
from tests.test_xbrl_esef_fetch import LEI
from tests.test_xbrl_esef_fetch import FakeSource as EsefFake
from tests.test_xbrl_fetch import FakeSource as SecFake

COMPANIES = [
    CompanyRef(company_id="us", name="US Co", cik="1234567"),
    CompanyRef(company_id="de", name="DE Co", country="Germany", lei=LEI),
    CompanyRef(company_id="jp", name="JP Co", isin="JP3633400001"),
    CompanyRef(company_id="nn", name="Name Only"),
]


@pytest.fixture
def env(tmp_path):
    return Settings(xbrl_dir=tmp_path / "xbrl", runs_dir=tmp_path / "runs"), RunStore(tmp_path / "runs")


@pytest.fixture(autouse=True)
def _nosleep(monkeypatch):
    async def fast(_):
        return None

    monkeypatch.setattr("asyncio.sleep", fast)


async def _run(env, run_id, companies, **kw):
    settings, runs = env
    kw.setdefault("source", SecFake())
    kw.setdefault("esef_source", EsefFake())
    await execute_xbrl_run(run_id, companies, settings=settings, run_store=runs, tags=None, refresh=False,
                           market="auto", **kw)
    return {r["company_id"]: r for r in runs.read_jsonl(runs.results_path(run_id))}


async def test_auto_run_fetches_each_company_by_its_route(env):
    _, runs = env
    run_id = create_xbrl_run(COMPANIES, None, False, runs, market="auto")
    rows = await _run(env, run_id, COMPANIES)
    assert {k: v["status"] for k, v in rows.items()} == {"us": "ok", "de": "ok", "jp": "no_source", "nn": "unrouted"}
    assert (rows["us"]["market"], rows["de"]["market"]) == ("sec", "esef")
    for cid in ("jp", "nn"):
        assert rows[cid]["market"] is None and rows[cid]["note"] and rows[cid]["fact_count"] == 0
    assert runs.load_manifest(run_id).status.value == "completed"


def test_routing_json_written_and_enriched_companies_stored(env):
    _, runs = env
    idmap = IdentifierMapStore(env[0].xbrl_dir.parent / "idmap.jsonl")
    idmap.add(IdentifierMap(issuer_key="K1", scheme="ISIN", value="XS0000000001"))
    idmap.add(IdentifierMap(issuer_key="K1", scheme="CIK", value="1234567"))
    co = CompanyRef(company_id="x", name="X", isin="XS0000000001")
    run_id = create_xbrl_run([co], None, False, runs, market="auto", index=MasterIndex.build(idmap))
    entry = json.loads((runs.run_dir(run_id) / "routing.json").read_text())[0]
    assert {k: entry[k] for k in ("company_id", "market", "status", "basis")} == {
        "company_id": "x", "market": "sec", "status": "routed", "basis": "master"}
    assert entry["detail"] and entry["company"]["cik"] == "1234567"
    assert runs.load_companies(run_id)[0].cik == "1234567"
    assert load_routing(runs, run_id)["x"]["market"] == "sec"
    assert runs.load_manifest(run_id).params["market"] == "auto"


class _CikSpy(SecFake):
    def __init__(self) -> None:
        super().__init__(cik="9999999")  # what an unrouted lookup would give
        self.ciks: list[str | None] = []

    async def resolve_cik(self, cik, ticker):
        self.ciks.append(cik)
        return await super().resolve_cik(cik, ticker)


async def test_resume_and_retry_keep_the_original_routing(env):
    _, runs = env
    idmap = IdentifierMapStore(env[0].xbrl_dir.parent / "idmap.jsonl")
    idmap.add(IdentifierMap(issuer_key="K1", scheme="ISIN", value="XS0000000001"))
    idmap.add(IdentifierMap(issuer_key="K1", scheme="CIK", value="1234567"))
    co = CompanyRef(company_id="x", name="X", isin="XS0000000001")
    run_id = create_xbrl_run([co], None, False, runs, market="auto", index=MasterIndex.build(idmap))
    # the master changes after the run was created: the ISIN now points at two issuers
    idmap.add(IdentifierMap(issuer_key="K2", scheme="ISIN", value="XS0000000001"))
    path = runs.run_dir(run_id) / "routing.json"
    before = path.read_bytes()
    sec = _CikSpy()
    rows = await _run(env, run_id, [co], source=sec)  # the master is not consulted again
    assert rows["x"]["status"] == "ok" and sec.ciks == ["1234567"]
    again = await _run(env, run_id, [co])
    assert again["x"]["status"] == "ok" and path.read_bytes() == before


async def test_rule_1_row_is_stored_and_fetched_with_the_master_lei(env):
    _, runs = env
    idmap = IdentifierMapStore(env[0].xbrl_dir.parent / "idmap.jsonl")
    idmap.add(IdentifierMap(issuer_key="K1", scheme="ISIN", value="DE0007164600"))
    idmap.add(IdentifierMap(issuer_key="K1", scheme="LEI", value=LEI))
    co = CompanyRef(company_id="sap", name="SAP", country="DE", isin="DE0007164600")
    run_id = create_xbrl_run([co], None, False, runs, market="auto", index=MasterIndex.build(idmap))
    entry = json.loads((runs.run_dir(run_id) / "routing.json").read_text())[0]
    assert (entry["basis"], entry["company"]["lei"]) == ("country", LEI)
    assert runs.load_companies(run_id)[0].lei == LEI
    esef = EsefFake()
    rows = await _run(env, run_id, [co], esef_source=esef)  # the un-enriched row is passed in
    assert rows["sap"]["status"] == "ok" and esef.asked == [LEI]


async def test_company_missing_from_stored_routing_is_unrouted(env):
    _, runs = env
    run_id = create_xbrl_run(COMPANIES[:1], None, False, runs, market="auto")
    sec = SecFake()
    rows = await _run(env, run_id, [CompanyRef(company_id="new", name="New", cik="7654321")], source=sec)
    assert (rows["new"]["status"], rows["new"]["note"], rows["new"]["market"]) == (
        "unrouted", "not in stored routing", None)
    assert not sec.calls


async def test_missing_routing_json_is_created_from_stored_companies(env):
    _, runs = env
    run_id = create_xbrl_run(COMPANIES, None, False, runs, market="sec")
    runs.manifest_path(run_id).write_text(
        runs.manifest_path(run_id).read_text().replace('"market": "sec"', '"market": "auto"'))
    rows = await _run(env, run_id, runs.load_companies(run_id))
    assert rows["nn"]["status"] == "unrouted" and (runs.run_dir(run_id) / "routing.json").exists()


async def test_forced_markets_ignore_routing(env):
    settings, runs = env
    sec = SecFake()
    run_id = create_xbrl_run(COMPANIES[:1], None, False, runs, market="sec")
    await execute_xbrl_run(run_id, COMPANIES[:1], settings=settings, run_store=runs, tags=None, refresh=False,
                           market="sec", source=sec)
    assert not (runs.run_dir(run_id) / "routing.json").exists() and sec.calls
    # forced esef on a company auto would route to sec: still treated as ESEF (no LEI here)
    run_id = create_xbrl_run(COMPANIES[:1], None, False, runs, market="esef")
    await execute_xbrl_run(run_id, COMPANIES[:1], settings=settings, run_store=runs, tags=None, refresh=False,
                           market="esef", source=EsefFake())
    assert runs.read_jsonl(runs.results_path(run_id))[0]["status"] == "no_lei"


async def test_unrouted_rows_count_as_completed(env):
    _, runs = env
    run_id = create_xbrl_run(COMPANIES[2:], None, False, runs, market="auto")
    await _run(env, run_id, COMPANIES[2:])
    m = runs.load_manifest(run_id)
    assert (m.completed_count, m.failed_count) == (2, 0)


async def test_sources_built_lazily(env, monkeypatch):
    _, runs = env

    def boom(*a, **k):
        raise AssertionError("ESEF source built")

    monkeypatch.setattr("arp.xbrl_pipeline.fetch_esef.IndexEsefSource", boom)
    run_id = create_xbrl_run(COMPANIES[:1] + COMPANIES[2:], None, False, runs, market="auto")
    rows = await _run(env, run_id, COMPANIES[:1] + COMPANIES[2:], esef_source=None)
    assert rows["us"]["status"] == "ok"

    def boom_sec(*a, **k):
        raise AssertionError("SEC source built")

    monkeypatch.setattr("arp.xbrl_pipeline.fetch.build_source", boom_sec)
    run_id = create_xbrl_run(COMPANIES[1:], None, False, runs, market="auto")
    rows = await _run(env, run_id, COMPANIES[1:], source=None)
    assert rows["de"]["status"] == "ok"
