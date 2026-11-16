"""Spec workbench-review-fixes, speed PR: the compact latest-observations file, the start-up fill, parallel reads and
compressed responses."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("zen")

from arp.api.deps import get_portfolio_store, get_run_store, get_stream_store  # noqa: E402
from arp.api.main import app  # noqa: E402
from arp.config import get_settings  # noqa: E402
from arp.schemas.common import CompanyRef, RunManifest  # noqa: E402
from arp.schemas.portfolio import DataPointObservation, Holding, Portfolio, SecurityRef  # noqa: E402
from arp.stewardship import universe  # noqa: E402
from arp.stewardship.process import StreamStore  # noqa: E402
from arp.stewardship.universe import HouseUniverseSetting, fill_observation_cache  # noqa: E402
from arp.storage import portfolio_store  # noqa: E402
from arp.storage.portfolio_store import LATEST_FILE, PortfolioStore  # noqa: E402
from arp.storage.portfolio_store_factory import build_portfolio_store  # noqa: E402
from arp.storage.run_store import RunStore  # noqa: E402
from tests.postgres_helpers import replace_results  # noqa: E402

SNAPSHOT = "2026-11-02"
COMPANIES = [f"C{n}" for n in range(6)]
FIELDS = ("transition_grade", "esg_score", "ghg_intensity", "climate_evic_eur_m")


def _obs(cid: str, fid: str, value, observed_at: str = "2026-11-01", source: str = "simulated") -> DataPointObservation:
    return DataPointObservation(company_id=cid, field_id=fid, field_name=fid, value=value, source=source, observed_at=observed_at)


def _fill_store(store) -> None:
    """One fund holding six companies, four observation fields each, read as of the snapshot."""
    store.save_portfolio(Portfolio(portfolio_id="P1", name="Fund P1"))
    for n, cid in enumerate(COMPANIES):
        store.save_company(CompanyRef(company_id=cid, name=f"Company {cid}", sector="Energy"))
        store.save_security(SecurityRef(security_id=f"{cid}-EQ", name=cid, asset_class="equity", currency="EUR", company_id=cid))
        for fid in FIELDS:
            store.append_observation(_obs(cid, fid, "BCDEFA"[n] if fid == "transition_grade" else float(n + 1)))
    store.save_snapshot("P1", SNAPSHOT, [
        Holding(holder_id="P1", security_id=f"{cid}-EQ", as_of_date=SNAPSHOT, market_value_eur=(n + 1) * 1e6) for n, cid in enumerate(COMPANIES)
    ])  # fmt: skip


def _forget_cache() -> None:
    """What a new server process starts with."""
    portfolio_store._LATEST.clear()


def _entries(store: PortfolioStore) -> list:
    return json.loads((store.portfolios_dir / LATEST_FILE).read_text())


@pytest.fixture
def files(tmp_path):
    store = PortfolioStore(tmp_path / "pf")
    _fill_store(store)
    yield store
    _forget_cache()


def test_fill_writes_the_compact_file_when_it_is_missing(files):
    # AC-8
    assert not (files.portfolios_dir / LATEST_FILE).exists()
    fill_observation_cache(files)
    entries = _entries(files)
    assert sorted((e[0], e[1]) for e in entries) == files.list_observation_keys() and len(entries) == len(COMPANIES) * len(FIELDS)


def test_fill_does_not_rewrite_a_compact_file_that_is_up_to_date(files):
    fill_observation_cache(files)
    before = (files.portfolios_dir / LATEST_FILE).stat().st_mtime_ns
    _forget_cache()
    fill_observation_cache(files)
    assert (files.portfolios_dir / LATEST_FILE).stat().st_mtime_ns == before


def test_a_new_process_seeded_from_the_compact_file_sees_an_appended_observation(files):
    # AC-4
    fill_observation_cache(files)
    files.append_observation(_obs("C2", "transition_grade", "A", observed_at="2026-11-02"))
    script = (
        "import sys; from pathlib import Path; from arp.storage.portfolio_store import PortfolioStore\n"
        "store = PortfolioStore(Path(sys.argv[1])); seeded = store.seed_latest_observations()\n"
        "print(len(seeded), store.latest_observation('C2', 'transition_grade', sys.argv[2]).value)"
    )
    out = subprocess.run([sys.executable, "-c", script, str(files.portfolios_dir), SNAPSHOT], capture_output=True, text=True, check=True)
    assert out.stdout.split() == [str(len(COMPANIES) * len(FIELDS)), "A"]


def test_a_seeded_entry_whose_file_is_unchanged_is_not_read_again(files, monkeypatch):
    fill_observation_cache(files)
    _forget_cache()
    files.seed_latest_observations()
    monkeypatch.setattr(PortfolioStore, "_read_jsonl", lambda path: pytest.fail(f"read {path}"))
    assert files.latest_observation("C1", "esg_score", SNAPSHOT).value == 2.0


def test_the_compact_file_entry_for_another_as_of_is_read_again(files):
    fill_observation_cache(files)
    _forget_cache()
    files.seed_latest_observations()
    assert files.latest_observation("C1", "esg_score", "2026-10-31") is None  # observed 2026-11-01


# --- through the API, on the portfolio universe ---


@pytest.fixture
def house(sample_house_universe, pg, monkeypatch, tmp_path):
    monkeypatch.setenv("ARP_ENGAGEMENTS_DIR", str(tmp_path / "engagements"))
    monkeypatch.setenv("ARP_ENGAGEMENT_STORE", "postgres")
    monkeypatch.setenv("ARP_PORTFOLIOS_DIR", str(tmp_path / "portfolios"))
    get_settings.cache_clear()
    get_portfolio_store.cache_clear()
    settings = get_settings()
    _fill_store(build_portfolio_store(settings))
    HouseUniverseSetting(settings.stewardship_streams_dir).set("portfolio", "tests")
    app.dependency_overrides[get_stream_store] = lambda: StreamStore(settings.stewardship_streams_dir)
    yield settings
    app.dependency_overrides.pop(get_stream_store, None)
    get_portfolio_store.cache_clear()
    _forget_cache()


def _worklist(**headers) -> tuple[dict, float]:
    """The worklist of a freshly started server, and how long start-up and the request took."""
    start = time.perf_counter()
    with TestClient(app) as client:
        r = client.get("/api/stewardship/worklist", headers=headers)
        elapsed = time.perf_counter() - start
    assert r.status_code == 200, r.text
    return r.json(), elapsed


@pytest.mark.parametrize("content", [None, "", "{"])
def test_a_missing_or_damaged_compact_file_only_costs_speed(house, content, caplog):
    # AC-5
    expected, _ = _worklist()  # the start-up fill wrote a good compact file
    assert expected["rows"] and len(_entries(PortfolioStore(house.portfolios_dir))) == len(COMPANIES) * len(FIELDS)
    path = house.portfolios_dir / LATEST_FILE
    path.unlink()
    if content is not None:
        path.write_text(content)
    _forget_cache()
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        body, _ = _worklist()
    assert body == expected
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING and str(path) in r.getMessage()]
    assert len(warnings) == (0 if content is None else 1), [r.getMessage() for r in caplog.records]


def test_the_compact_file_changes_nothing(house, monkeypatch):
    # AC-9 (the parallel reads were measured slower on the showcase house and left out: see the PR)
    seeded, _ = _worklist()
    _forget_cache()
    (house.portfolios_dir / LATEST_FILE).unlink()
    monkeypatch.setattr(universe, "start_fill", lambda store: None)  # no start-up fill, no compact file
    plain, _ = _worklist()
    assert not (house.portfolios_dir / LATEST_FILE).exists()
    assert len(seeded["rows"]) == len(COMPANIES) and seeded == plain


def test_the_worklist_is_sent_compressed(house):
    # AC-7 (holdout checks it on the showcase house)
    with TestClient(app) as client:
        plain = client.get("/api/stewardship/worklist", headers={"Accept-Encoding": "identity"})
        zipped = client.get("/api/stewardship/worklist", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in plain.headers and zipped.headers["content-encoding"] == "gzip"
    assert zipped.content == plain.content  # httpx unzips


def test_a_request_waits_at_most_the_fill_limit(house, monkeypatch):
    # AC-28: the start-up fill never finishes; a request waits FILL_WAIT_S at most, then reads the files itself
    release = threading.Event()
    monkeypatch.setattr(universe, "FILL_WAIT_S", 1)

    def get(client, hang: bool) -> tuple[dict, float]:
        _forget_cache()
        with monkeypatch.context() as m:
            m.setattr(universe, "fill_observation_cache", (lambda store: release.wait()) if hang else (lambda store: None))
            universe.start_fill(build_portfolio_store(house))
            if not hang:
                universe.wait_for_fill()
                time.sleep(universe.FILL_WAIT_S)  # the read after a hanging fill follows an idle second: so does this one
            start = time.perf_counter()
            r = client.get("/api/stewardship/worklist")
            elapsed = time.perf_counter() - start
        assert r.status_code == 200, r.text
        return r.json(), elapsed

    try:
        with TestClient(app) as client:
            expected, _ = get(client, hang=False)
            # a normal read is the slowest of three: the reads vary by +-10 ms on this fixture, a min-to-min compare is a coin toss
            normal = max(get(client, hang=False)[1] for _ in range(3))
            waited = []
            for _ in range(3):  # best of three: one slow run on a busy machine is not a failure
                body, elapsed = get(client, hang=True)
                assert body == expected and not universe._filled.is_set()
                waited.append(elapsed)
        assert 1 <= min(waited) < 1 + normal, (waited, normal)
        _forget_cache()
        body, elapsed = _worklist()  # a hanging fill at start-up: the server still starts after FILL_WAIT_S
        assert body == expected and elapsed < 1 + 10 * normal + 2, elapsed
    finally:
        release.set()


def test_csv_export_content_is_the_same_compressed(tmp_path, pg):
    # AC-27
    store = RunStore(pg, tmp_path)
    store.save_manifest(RunManifest(run_id="r1", run_type="extraction"))
    field = {"field_name": "x", "confidence": 0.9, "grounded": True, "value": 1.5, "unit": "USD", "value_state": "found"}
    replace_results(store, "r1", [{"company_id": f"c{n}", "ticker": "T", "name": "N", "needs_review": False, "fields": [field]} for n in range(200)])
    app.dependency_overrides[get_run_store] = lambda: store
    try:
        client = TestClient(app)
        plain = client.get("/api/runs/r1/export.csv", headers={"Accept-Encoding": "identity"})
        zipped = client.get("/api/runs/r1/export.csv", headers={"Accept-Encoding": "gzip"})
    finally:
        app.dependency_overrides.pop(get_run_store, None)
    assert plain.status_code == 200 and len(plain.content) > 1000
    assert zipped.headers["content-encoding"] == "gzip" and zipped.content == plain.content


def test_the_compact_file_sits_outside_datapoints(files):
    fill_observation_cache(files)
    assert Path(files.portfolios_dir / LATEST_FILE).exists() and len(files.list_observation_keys()) == len(COMPANIES) * len(FIELDS)
