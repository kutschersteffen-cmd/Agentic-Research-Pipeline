"""Spec stewardship-house-universe-cache: the house universe built once per process and rebuilt when an input changes.

Store S: two held companies (C1, C2) in one portfolio with two holdings snapshot dates, two observation files, source
`portfolio`. The `main` answers (AC-38, AC-39, AC-41) were recorded from `main` d92366c5 (#544 and #548 merged) before
the build changed any code: `ARP_RECORD_MAIN_ANSWERS=1 pytest tests/test_house_universe_cache.py -k record` rewrites them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("zen")

from arp.api.deps import get_portfolio_store, get_stream_store  # noqa: E402
from arp.api.main import app  # noqa: E402
from arp.config import get_settings  # noqa: E402
from arp.portfolio.loads import LoadRecord, record_load  # noqa: E402
from arp.schemas.common import CompanyRef  # noqa: E402
from arp.schemas.portfolio import DataPointObservation, Holding, Portfolio, SecurityRef, SecurityResolution  # noqa: E402
from arp.stewardship.intake import intake_votes  # noqa: E402
from arp.stewardship.process import StreamStore  # noqa: E402
from arp.stewardship.universe import HouseUniverseSetting  # noqa: E402
from arp.storage import portfolio_store  # noqa: E402
from arp.storage.portfolio_store_factory import build_portfolio_store  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "house_universe_cache"
RECORD = os.environ.get("ARP_RECORD_MAIN_ANSWERS") == "1"
DATES = ("2026-09-30", "2026-10-31")
MONTH = "2026-09"  # the earlier month, for the monthly run (AC-41)
ENDPOINTS = (
    "/api/stewardship/worklist?scope=house", "/api/stewardship/worklist/scopes", "/api/stewardship/selection",
    "/api/stewardship/tiers", "/api/stewardship/decision-inputs", "/api/stewardship/studio/coverage/inputs",
    "/api/stewardship/studio/monitoring/triggers", "/api/stewardship/streams/house/flow",
)  # fmt: skip


def fill_store_s(store) -> None:
    """Store S's data, written through the (Postgres) portfolio store."""
    store.save_portfolio(Portfolio(portfolio_id="P1", name="Fund P1"))
    for n, cid in enumerate(("C1", "C2"), 1):
        store.save_company(CompanyRef(company_id=cid, name=f"Company {cid}", sector="Energy", country="DE"))
        store.save_security(SecurityRef(security_id=f"{cid}-EQ", name=cid, asset_class="equity", currency="EUR", company_id=cid, isin=f"DE000000000{n}"))
        store.save_resolution(SecurityResolution(security_id=f"{cid}-EQ", company_id=cid, confidence=1.0))
    for k, day in enumerate(DATES):
        store.save_snapshot("P1", day, [
            Holding(holder_id="P1", security_id=f"{cid}-EQ", as_of_date=day, market_value_eur=(n + k) * 1e6, isin=f"DE000000000{n}")
            for n, cid in enumerate(("C1", "C2"), 1)
        ])  # fmt: skip
    for cid, value in (("C1", 120.0), ("C2", 80.0)):  # the two observation files
        store.append_observation(DataPointObservation(company_id=cid, field_id="ghg_intensity", field_name="ghg_intensity", value=value, source="internal_api", observed_at="2026-09-15"))
    for kind, source in (("holdings", "P1"), ("esg", "default")):
        record_load(store, LoadRecord(kind=kind, source_id=source, month=MONTH, status="ok", content_hash="h"))
    # one vote-ledger meeting on C1's ISIN, so the vote ledger maps ISINs to house issuers (the held ISIN map)
    vote = {"external_id": "v1", "isin": "DE0000000001", "issuer_name": "Company C1", "meeting_date": "2026-05-01",
            "item_number": "1", "description": "x", "management_recommendation": "for", "vote": "for"}  # fmt: skip
    assert intake_votes([vote], get_settings().postgres_dsn, "api").rejected == []


@pytest.fixture
def store_s(pg, monkeypatch, tmp_path):
    for name, sub in (("ARP_PORTFOLIOS_DIR", "portfolios"), ("ARP_STEWARDSHIP_STREAMS_DIR", "streams"), ("ARP_ENGAGEMENTS_DIR", "engagements"),
                      ("ARP_FRAMEWORKS_DIR", "frameworks"), ("ARP_RUNS_DIR", "runs")):  # fmt: skip
        monkeypatch.setenv(name, str(tmp_path / sub))
    monkeypatch.setenv("ARP_ENGAGEMENT_STORE", "postgres")
    get_settings.cache_clear()
    get_portfolio_store.cache_clear()
    settings = get_settings()
    store = build_portfolio_store(settings)
    fill_store_s(store)
    HouseUniverseSetting(settings.stewardship_streams_dir).set("portfolio", "tests")
    app.dependency_overrides[get_stream_store] = lambda: StreamStore(settings.stewardship_streams_dir)
    yield store
    app.dependency_overrides.pop(get_stream_store, None)
    get_portfolio_store.cache_clear()
    portfolio_store._LATEST.clear()


@pytest.fixture
def fixture_w(sample_house_universe, pg, monkeypatch, tmp_path):
    monkeypatch.setenv("ARP_ENGAGEMENTS_DIR", str(tmp_path / "engagements"))
    monkeypatch.setenv("ARP_ENGAGEMENT_STORE", "postgres")
    monkeypatch.setenv("ARP_PORTFOLIOS_DIR", str(tmp_path / "portfolios"))
    get_settings.cache_clear()
    root = get_settings().stewardship_streams_dir
    app.dependency_overrides[get_stream_store] = lambda: StreamStore(root)
    yield
    app.dependency_overrides.pop(get_stream_store, None)


def answers() -> dict:
    with TestClient(app) as client:
        out = {}
        for url in ENDPOINTS:
            r = client.get(url)
            assert r.status_code == 200, (url, r.text)
            body = r.json()
            body.pop("cycle", None)  # the current quarter (worklist, selection)
            if url.startswith("/api/stewardship/worklist?"):
                body.pop("as_of")  # today's date
            out[url] = body
    return out


def _record(name: str, value) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / name).write_text(json.dumps(value, indent=1, sort_keys=True, default=str) + "\n")


@pytest.mark.skipif(not RECORD, reason="records the main answers; set ARP_RECORD_MAIN_ANSWERS=1")
def test_record_main_answers_store_s(store_s):
    _record("main_answers_store_s.json", answers())


@pytest.mark.skipif(not RECORD, reason="records the main answers; set ARP_RECORD_MAIN_ANSWERS=1")
def test_record_main_answers_fixture_w(fixture_w):
    _record("main_answers_fixture_w.json", answers())


@pytest.mark.skipif(not RECORD, reason="records the main answers; set ARP_RECORD_MAIN_ANSWERS=1")
def test_record_main_latest_format():
    _record("main_latest_format.json", {"format": portfolio_store._latest_format()})


@pytest.mark.skipif(not RECORD, reason="records the main answers; set ARP_RECORD_MAIN_ANSWERS=1")
def test_record_main_monthly_run(store_s, monkeypatch):
    from arp.portfolio import monthly_run
    from arp.stewardship import process

    seen: dict = {}
    real_load_sample, real_house_isins = monthly_run.load_sample, process.house_isins
    monkeypatch.setattr(monthly_run, "load_sample", lambda *a, **k: seen.setdefault("universe", a[3]) and real_load_sample(*a, **k))
    monkeypatch.setattr(process, "house_isins", lambda: seen.setdefault("held_isins", real_house_isins()))
    result = monthly_run.run_month(store_s, get_settings(), MONTH, portfolio_ids=["P1"])
    assert result.status == "ran", result
    _record("main_monthly_run.json", {"universe": seen["universe"], "held_isins": seen.get("held_isins")})


# --- the unit rows ---

import logging  # noqa: E402
import shutil  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from sqlalchemy import text  # noqa: E402

from arp.db.session import transaction  # noqa: E402
from arp.stewardship import process, universe  # noqa: E402

LOGGER = "arp.stewardship.universe"
BUILT, CHECKED = "House universe built:", "Input check:"


@pytest.fixture(autouse=True)
def _no_kept_build():
    universe.clear_kept_build()
    yield
    universe.clear_kept_build()


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    return lambda prefix: [r for r in caplog.records if r.name == LOGGER and r.getMessage().startswith(prefix)]


def _ghg(result: dict, cid: str = "C1"):
    return next(i for i in result["issuers"] if i["issuer_id"] == cid)["fields"].get("portfolio.ghg_intensity")


def _append(store, value: float, cid: str = "C1") -> None:
    store.append_observation(DataPointObservation(company_id=cid, field_id="ghg_intensity", field_name="ghg_intensity", value=value, source="internal_api", observed_at="2026-10-01"))


def _slow(monkeypatch, *, before: float = 0.0, after: float = 0.0, fail_first: bool = False) -> None:
    """The build (`from_portfolio` inside it) waits `before` s, then builds, then waits `after` s; `fail_first`: the
    first build raises RuntimeError("boom") after its wait."""
    real, calls = process.from_portfolio, []

    def build(*args, **kwargs):
        calls.append(1)
        time.sleep(before)
        if fail_first and len(calls) == 1:
            raise RuntimeError("boom")
        result = real(*args, **kwargs)
        time.sleep(after)
        return result

    monkeypatch.setattr(process, "from_portfolio", build)


def _in_threads(n: int, fn) -> list:
    out: list = [None] * n

    def run(k):
        try:
            out[k] = fn()
        except Exception as exc:  # noqa: BLE001 -- the result under test
            out[k] = exc

    threads = [threading.Thread(target=run, args=(k,)) for k in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def test_an_unchanged_input_builds_once(store_s, logs):
    # AC-20
    first = process.house_universe()
    assert process.house_universe() == first and len(first["issuers"]) == 2
    assert len(logs(BUILT)) == 1


def test_parallel_calls_share_one_build(store_s, logs, monkeypatch):
    # AC-21
    _slow(monkeypatch, before=1)
    results = _in_threads(8, process.house_universe)
    assert len(logs(BUILT)) == 1 and all(r == results[0] for r in results) and len(results[0]["issuers"]) == 2


def test_a_failed_build_is_not_kept(store_s, logs, monkeypatch):
    # AC-22
    _slow(monkeypatch, before=1, fail_first=True)
    results = _in_threads(4, process.house_universe)
    assert all(isinstance(r, RuntimeError) and str(r) == "boom" for r in results), results
    assert len(process.house_universe()["issuers"]) == 2 and len(logs(BUILT)) == 1


def test_a_change_during_a_running_check_is_seen(store_s, monkeypatch):
    # AC-23, with a kept build in place, so a check that started before the change would return it unchanged
    process.house_universe()
    real = universe._observation_files
    monkeypatch.setattr(universe, "_observation_files", lambda d: (real(d), time.sleep(1))[0])
    results: dict = {}
    a = threading.Thread(target=lambda: results.setdefault("a", process.house_universe()))
    a.start()
    time.sleep(0.5)
    _append(store_s, 333.0)
    results["b"] = process.house_universe()
    a.join()
    assert _ghg(results["b"]) == 333.0


def test_parallel_calls_share_the_check(store_s, logs):
    # AC-24
    process.house_universe()
    before = len(logs(CHECKED))
    _in_threads(6, process.house_universe)
    assert len(logs(CHECKED)) - before <= 2


def test_a_caller_never_changes_another_callers_universe(store_s):
    # AC-25
    process.house_universe()["issuers"][0]["fields"]["probe"] = 1
    assert "probe" not in process.house_universe()["issuers"][0]["fields"]


def test_the_sample_is_copied_too(fixture_w):
    # AC-40
    process.house_universe()["issuers"][0]["fields"]["probe"] = 1
    assert "probe" not in process.house_universe()["issuers"][0]["fields"]


@pytest.mark.parametrize("data", ["store_s", "fixture_w"])
def test_a_kept_answer_equals_a_fresh_one(data, request):
    # AC-26
    request.getfixturevalue(data)
    with TestClient(app) as client:
        for url in ENDPOINTS:
            universe.clear_kept_build()
            fresh = client.get(url)
            kept = client.get(url)
            assert fresh.status_code == kept.status_code == 200, (url, fresh.text)
            assert fresh.json() == kept.json(), url


@pytest.mark.parametrize(("data", "fixture"), [("store_s", "main_answers_store_s.json"), ("fixture_w", "main_answers_fixture_w.json")])
def test_every_answer_equals_main(data, fixture, request):
    # AC-38
    request.getfixturevalue(data)
    assert answers() == json.loads((FIXTURES / fixture).read_text())


def test_a_published_decision_reaches_load_sample(store_s):
    # AC-27
    from arp.schemas.decision import PublishedDecision, PublishedRow
    from arp.storage.decision_store import DecisionStore

    process.house_universe()
    DecisionStore(get_settings().frameworks_dir).save_published(PublishedDecision(
        framework_id="fw", framework_version=1, framework_name="F", dataset_id="d", dataset_name="D", id_column="id",
        published_by="A", rows=[PublishedRow(entity_id="C1", name="Company C1", score=72.5, tier=1)],
    ))  # fmt: skip
    c1 = next(i for i in process.load_sample()["issuers"] if i["issuer_id"] == "C1")
    assert c1["fields"]["decision.fw.tier"] == 1


def test_one_check_per_request(store_s, logs):
    # AC-28
    process.house_universe()
    with TestClient(app) as client:
        for url in ENDPOINTS:
            before = len(logs(CHECKED))
            assert client.get(url).status_code == 200, url
            assert len(logs(CHECKED)) - before == 1, url


def test_a_read_through_the_observation_cache_does_not_hide_a_change(store_s):
    # AC-30
    process.house_universe()
    _append(store_s, 444.0)
    assert store_s.latest_observation("C1", "ghg_intensity", DATES[-1]).value == 444.0
    assert _ghg(process.house_universe()) == 444.0


def test_every_input_change_rebuilds(store_s, logs):
    # AC-31
    settings = get_settings()
    process.house_universe()
    datapoints = settings.portfolios_dir / "datapoints"

    def fresh() -> dict:
        universe.clear_kept_build()
        return process.house_universe()

    changes = [
        lambda: _sql("UPDATE securities SET name = 'Changed' WHERE security_id = 'C1-EQ'"),
        lambda: _sql("UPDATE security_resolutions SET confidence = 0.5 WHERE security_id = 'C2-EQ'"),
        lambda: _sql("UPDATE portfolios SET name = 'Fund P1 renamed' WHERE portfolio_id = 'P1'"),
        lambda: store_s.append_observation(DataPointObservation(company_id="C2", field_id="esg_score", field_name="esg_score", value=5.0, source="internal_api", observed_at="2026-10-01")),
        lambda: (datapoints / "C2" / "esg_score.jsonl").unlink(),
    ]  # fmt: skip
    for change in changes:
        builds = len(logs(BUILT))
        change()
        result = process.house_universe()
        assert len(logs(BUILT)) == builds + 1
        assert result == fresh()


def _sql(statement: str) -> None:
    with transaction(get_settings().postgres_dsn) as s:
        assert s.execute(text(statement)).rowcount == 1, statement


def test_a_changed_sample_file_rebuilds(fixture_w, tmp_path, monkeypatch):
    # AC-32
    sample = tmp_path / "sample_meetings.json"
    shutil.copy(process.SAMPLE_PATH, sample)
    monkeypatch.setattr(process, "SAMPLE_PATH", sample)
    first = process.house_universe()
    data = json.loads(sample.read_text())
    data["issuers"] = data["issuers"][1:]
    (tmp_path / "next.json").write_text(json.dumps(data))
    os.replace(tmp_path / "next.json", sample)
    assert len(process.house_universe()["issuers"]) == len(first["issuers"]) - 1


def _tree(*roots: Path) -> dict:
    return {p: p.stat().st_mtime_ns for root in roots if root.exists() for p in root.rglob("*")}


def test_nothing_is_stored(store_s):
    # AC-33: the calls themselves create or change no file (the test's own change excepted)
    settings = get_settings()
    roots = (settings.portfolios_dir, settings.stewardship_streams_dir, settings.identifier_map_path.parent)
    before = _tree(*roots)
    process.house_universe()
    assert _tree(*roots) == before
    _append(store_s, 555.0)
    changed = _tree(*roots)
    process.house_universe()  # a rebuild
    assert _tree(*roots) == changed


def test_a_change_during_a_build_rebuilds_on_the_next_call(store_s, logs, monkeypatch):
    # AC-36
    _slow(monkeypatch, before=1)
    first = threading.Thread(target=process.house_universe)
    first.start()
    time.sleep(0.5)
    _append(store_s, 666.0)
    first.join()
    assert _ghg(process.house_universe()) == 666.0 and len(logs(BUILT)) == 2


def test_new_folders_rebuild(store_s, logs, monkeypatch, tmp_path):
    # AC-37
    settings = get_settings()
    process.house_universe()
    new = tmp_path / "moved"
    shutil.copytree(settings.portfolios_dir / "datapoints", new / "portfolios" / "datapoints")
    (new / "map").mkdir()
    (new / "map" / "issuer_sectors.json").write_text(json.dumps({"C1": {"sector": "S2 Sector"}}))
    monkeypatch.setenv("ARP_PORTFOLIOS_DIR", str(new / "portfolios"))
    monkeypatch.setenv("ARP_STEWARDSHIP_STREAMS_DIR", str(new / "streams"))
    monkeypatch.setenv("ARP_IDENTIFIER_MAP_PATH", str(new / "map" / "identifier_map.jsonl"))
    get_settings.cache_clear()
    HouseUniverseSetting(get_settings().stewardship_streams_dir).set("portfolio", "tests")
    c1 = next(i for i in process.house_universe()["issuers"] if i["issuer_id"] == "C1")
    assert c1["sector"] == "S2 Sector" and len(logs(BUILT)) == 2


def test_the_compact_file_written_before_the_build_stays_valid(store_s):
    # AC-39
    from arp.stewardship.universe import fill_observation_cache

    fill_observation_cache(store_s)
    path = get_settings().portfolios_dir / portfolio_store.LATEST_FILE
    data = json.loads(path.read_text())
    assert data["format"] == json.loads((FIXTURES / "main_latest_format.json").read_text())["format"]
    content, mtime = path.read_bytes(), path.stat().st_mtime_ns
    portfolio_store._LATEST.clear()
    with TestClient(app):  # start-up waits for the fill
        pass
    assert path.read_bytes() == content and path.stat().st_mtime_ns == mtime


def test_the_monthly_run_is_unchanged(store_s, monkeypatch):
    # AC-41
    from arp.portfolio import monthly_run

    process.house_universe()  # a kept build of the latest date exists
    seen: dict = {}
    real_load_sample, real_house_isins = monthly_run.load_sample, process.house_isins
    monkeypatch.setattr(monthly_run, "load_sample", lambda *a, **k: seen.setdefault("universe", a[3]) and real_load_sample(*a, **k))
    monkeypatch.setattr(process, "house_isins", lambda: seen.setdefault("held_isins", real_house_isins()))
    assert monthly_run.run_month(store_s, get_settings(), MONTH, portfolio_ids=["P1"]).status == "ran"
    recorded = json.loads((FIXTURES / "main_monthly_run.json").read_text())
    assert json.loads(json.dumps({"universe": seen["universe"], "held_isins": seen.get("held_isins")}, default=str)) == recorded


def test_a_change_during_a_builds_pause_is_seen_by_the_next_caller(store_s, monkeypatch):
    # AC-42
    process.house_universe()
    _slow(monkeypatch, after=1)
    _append(store_s, 701.0)
    results: dict = {}
    a = threading.Thread(target=lambda: results.setdefault("a", process.house_universe()))
    a.start()
    time.sleep(0.5)
    _append(store_s, 702.0)
    results["b"] = process.house_universe()
    a.join()
    assert _ghg(results["b"]) == 702.0


def test_a_symlinked_observation_file_is_never_stale(store_s):
    # code review B2: the check follows a link to its target, as latest_observation does
    path = get_settings().portfolios_dir / "datapoints" / "C1" / "ghg_intensity.jsonl"
    target = path.with_name("target.data")
    path.rename(target)
    path.symlink_to(target)
    assert _ghg(process.house_universe()) == 120.0
    with target.open("a") as f:
        f.write(json.dumps({"company_id": "C1", "field_id": "ghg_intensity", "field_name": "ghg_intensity", "value": 999.0,
                            "source": "internal_api", "observed_at": "2026-10-01"}) + "\n")  # fmt: skip
    assert _ghg(process.house_universe()) == 999.0


def test_the_walk_needs_nothing_posix_only(store_s, monkeypatch):
    # code review B1: no O_DIRECTORY or dir_fd, so the check runs where they do not exist (Windows)
    monkeypatch.delattr(os, "O_DIRECTORY")
    assert len(process.house_universe()["issuers"]) == 2
