"""Which companies the house stewardship program covers.

Two sources, chosen by a person and stored as a house setting:

- `sample`: the synthetic sample (fictional companies, rich company data and
  meetings), selectable for demos.
- `portfolio`: the companies held in the house portfolios (Risk Monitoring), the default.
  Issuer ids are then the portfolio company ids, which Decision Studio
  publications, Proxy Voting ballots and Risk Monitoring alerts use too, so
  every handoff into stewardship matches.

The portfolio universe is in the same shape as the sample (like a client
benchmark in `benchmark.as_universe`). What the holdings export does not
carry is not invented: company fields are the latest portfolio data-point
observations plus a **placeholder** CLTI score, and there are no meetings
or synthetic engagement history.
"""

from __future__ import annotations

import gc
import json
import logging
import os
import threading
import time
from collections import defaultdict
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from arp.schemas.portfolio import DataPointObservation
from arp.stewardship.benchmark import placeholder_clti
from arp.storage.atomic_io import atomic_write_text
from arp.storage.portfolio_store import PortfolioStore, portfolio_directories

SOURCES = ("sample", "portfolio")
FILL_WAIT_S = 60  # start-up and requests wait at most this long for the observation fill, then read the files themselves
logger = logging.getLogger(__name__)
_filled = threading.Event()
_filled.set()  # set: no start-up fill running
_fill_started = 0.0


class HouseUniverseSetting:
    def __init__(self, root: Path) -> None:
        # A subfolder: every *.json directly in the streams root is read as a client stream.
        self.path = root / "house" / "universe.json"

    def get(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {"source": "portfolio", "set_by": None, "set_at": None}

    def set(self, source: str, set_by: str) -> dict:
        if source not in SOURCES:
            raise ValueError(f"Unknown issuer source: {source}")
        if not set_by.strip():
            raise ValueError("Changing the issuer source needs set_by")
        setting = {"source": source, "set_by": set_by.strip(), "set_at": datetime.now(UTC).isoformat()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(setting))
        return setting


def held_isins(store: PortfolioStore, holdings=None, securities=None, resolutions=None) -> dict[str, str]:
    """ISIN -> house issuer id for the securities held in the latest snapshot, resolved as `from_portfolio` resolves
    them, so data keyed by ISIN (the vote ledger) reaches that issuer. The first holding of an ISIN wins.
    `holdings`, `securities`, `resolutions`: the latest snapshot's holdings and the two lookups, when already read."""
    if holdings is None:
        dates = store.all_snapshot_dates()
        if not dates:
            return {}
        holdings = store.load_holdings_as_of(dates[-1])
    securities = portfolio_directories(store)[0] if securities is None else securities
    resolutions = store.list_resolutions() if resolutions is None else resolutions
    out: dict[str, str] = {}
    for h in holdings:
        r, sec = resolutions.get(h.security_id), securities.get(h.security_id)
        isin = h.isin or (sec.isin if sec else None)
        if isin and r is not None and r.company_id:
            out.setdefault(isin.upper(), r.company_id)
    return out


def company_by_security(store: PortfolioStore, securities=None, resolutions=None) -> dict[str, str]:
    """security_id -> company_id: the security's resolution, else (no resolution at all) the company the security
    itself names, as the showcase import sets it without writing resolutions. `securities`, `resolutions`: when
    already read."""
    out = {}
    resolutions = store.list_resolutions() if resolutions is None else resolutions
    for sec in store.list_securities() if securities is None else securities:
        r = resolutions.get(sec.security_id)
        if cid := r.company_id if r is not None else sec.company_id:
            out[sec.security_id] = cid
    return out


def _value_by_company(holdings, companies: dict[str, str]) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for h in holdings:
        if cid := companies.get(h.security_id):
            out[cid] += h.market_value_eur
    return out


def fill_observation_cache(store: PortfolioStore) -> None:
    """Fills the per-file observation cache: from `observations_latest.json` first, then every entry is checked
    against its file and the changed ones read. If any file had to be read (compact file missing, damaged or out of
    date), the compact file is written again. One thread: on the showcase house 8 threads made the check 3x and a
    cold read 5x slower (the GIL)."""
    seeded = store.seed_latest_observations()
    dates = store.all_snapshot_dates()
    if not dates:
        return
    keys = store.list_observation_keys()
    for company_id, field_id in keys:
        store.latest_observation(company_id, field_id, dates[-1])
    store.save_latest_observations(keys, unchanged_from=seeded)


def start_fill(store: PortfolioStore) -> None:
    """`fill_observation_cache` in a background thread; start-up and `latest_observations` wait for it (`wait_for_fill`)
    instead of reading the same files at the same time. Best effort: a failure only leaves the cache cold."""
    global _fill_started

    def run() -> None:
        try:
            fill_observation_cache(store)
            gc.freeze()  # the ~81k cached observations live as long as the process: spare them every collector pass
        except Exception:  # noqa: BLE001 -- a cold cache is only slower, never wrong
            logger.warning("Could not fill the observation cache", exc_info=True)
        finally:
            _filled.set()

    _filled.clear()
    _fill_started = time.monotonic()
    threading.Thread(target=run, name="observation-fill", daemon=True).start()


def wait_for_fill() -> None:
    """Returns once the start-up fill is done, or FILL_WAIT_S after it started, whichever comes first."""
    _filled.wait(max(0.0, _fill_started + FILL_WAIT_S - time.monotonic()))


def latest_observations(store: PortfolioStore, as_of: str | None = None) -> dict[str, dict[str, DataPointObservation]]:
    """company_id -> {field_id: its latest observation as of `as_of` (default: the latest holdings snapshot)}, every
    recorded (company, field) pair read once."""
    wait_for_fill()
    dates = store.all_snapshot_dates()
    if not dates:
        return {}
    out: dict[str, dict[str, DataPointObservation]] = defaultdict(dict)
    for company_id, field_id in store.list_observation_keys():
        if (obs := store.latest_observation(company_id, field_id, as_of or dates[-1])) is not None:
            out[company_id][field_id] = obs
    return dict(out)


def from_portfolio(
    store: PortfolioStore, as_of: str | None = None, observations: dict | None = None, held_isins_out: dict | None = None
) -> dict:
    """The held companies in the shape of the synthetic sample. `as_of` dates the observation lookups (default: the
    latest holdings snapshot); `observations`: `latest_observations(store, as_of)` when the caller already read them;
    `held_isins_out`: filled with `held_isins(store)`, from the reads made here (the vote ledger needs it too)."""
    dates = store.all_snapshot_dates()
    if not dates:
        return {"source": "portfolio", "note": "No portfolio holdings loaded.", "issuers": [], "engagements": [], "meetings": []}
    obs_as_of, as_of = as_of or dates[-1], dates[-1]
    securities, companies = portfolio_directories(store)
    resolutions = store.list_resolutions()
    held = company_by_security(store, securities.values(), resolutions)
    latest = store.load_holdings_as_of(as_of)
    now = _value_by_company(latest, held)
    before = _value_by_company(store.load_holdings_as_of(dates[-2]), held) if len(dates) > 1 else {}
    if held_isins_out is not None:
        held_isins_out.update(held_isins(store, latest, securities, resolutions))
    total = sum(now.values())
    observed: dict[str, dict] = defaultdict(dict)
    simulated: set[str] = set()
    observations = latest_observations(store, obs_as_of) if observations is None else observations
    for company_id, by_field in observations.items():
        for field_id, obs in by_field.items():
            if isinstance(obs.value, int | float | bool):
                observed[company_id][f"portfolio.{field_id}"] = obs.value
                if obs.source == "simulated":
                    simulated.add(company_id)
    issuers = []
    for company_id, value in sorted(now.items(), key=lambda kv: -kv[1]):
        company = companies.get(company_id)
        issuers.append(
            {
                "issuer_id": company_id,
                "name": company.name if company else company_id,
                "region": (company.country if company else None) or "unknown",
                "sector": (company.sector if company else None) or "unknown",
                "fields": {"score.clti": placeholder_clti(company_id), **observed[company_id]},
                "holding": {
                    # No benchmark here: the weight is the company's share of all house holdings.
                    "index_weight_pct": round(value / total * 100, 3) if total else None,
                    "aum_held_eur_m": round(value / 1e6, 1),
                    "change_pct": round((value / before[company_id] - 1) * 100, 1) if before.get(company_id) else None,
                },
            }
        )
    return {
        "source": "portfolio",
        "note": f"Companies held in the house portfolios as of {as_of}. CLTI scores are placeholders; weights are the "
        "share of house holdings, not an index weight."
        + (f" Simulated: {n} of these companies carry simulated ESG values, not real data." if (n := len(simulated & now.keys())) else ""),
        "issuers": issuers,
        "engagements": [],
        "meetings": [],
    }


# --- the kept house build (spec stewardship-house-universe-cache) ---
#
# Per process, the last house build is kept and handed out as a copy while its inputs are unchanged. Every call
# works out the inputs' version first (the shared check below); nothing is stored, nothing is read from another
# process. Owner decision 16 Nov 2026: build once, rebuild when a holdings, data or settings input changes.

_VERSION_TABLES = ("holdings", "securities", "legacy_companies", "security_resolutions", "portfolios")
_VERSION_SQL = "SELECT " + ", ".join(
    f"(SELECT count(*) FROM {t}), (SELECT coalesce(sum(hashtextextended(r::text, 0)), 0) FROM {t} r)" for t in _VERSION_TABLES
)


@dataclass(frozen=True)
class HouseBuild:
    """The house universe with what was read to build it: `held` maps a held ISIN to its issuer (empty for the
    sample), `observations` is `latest_observations(store)` (None for the sample)."""

    universe: dict
    held: dict[str, str]
    observations: dict | None


def _identity(path: Path) -> tuple | None:
    """The identity #491 compares: inode, ctime, mtime and size; None for a missing file."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return (st.st_ino, st.st_ctime_ns, st.st_mtime_ns, st.st_size)


def _observation_files(portfolios_dir: Path) -> dict[tuple[str, str], tuple]:
    """(company folder, file name) -> identity of every observation file (`*.jsonl`, as list_observation_keys)."""
    out: dict[tuple[str, str], tuple] = {}
    try:
        companies = os.scandir(portfolios_dir / "datapoints")
    except FileNotFoundError:
        return out
    with companies:
        for company in companies:
            if company.is_dir():
                with os.scandir(company.path) as files:
                    for f in files:
                        if f.name.endswith(".jsonl") and f.is_file():
                            st = f.stat()
                            out[(company.name, f.name)] = (st.st_ino, st.st_ctime_ns, st.st_mtime_ns, st.st_size)
    return out


def input_version(settings) -> tuple:
    """Everything the house build reads, in a form that compares equal exactly when the build would be the same."""
    start = time.perf_counter()
    setting = HouseUniverseSetting(settings.stewardship_streams_dir)
    source = setting.get()["source"]
    paths = (settings.portfolios_dir, settings.stewardship_streams_dir, settings.identifier_map_path, settings.postgres_dsn)
    version: tuple = (paths, source, _identity(setting.path), _identity(settings.identifier_map_path.with_name("issuer_sectors.json")))
    files: dict = {}
    if source == "sample":
        from arp.stewardship.process import SAMPLE_PATH

        version += (_identity(SAMPLE_PATH),)
    else:
        from sqlalchemy import text

        from arp.db.session import transaction

        with transaction(settings.postgres_dsn) as s:
            version += (tuple(s.execute(text(_VERSION_SQL)).one()),)
        files = _observation_files(settings.portfolios_dir)
    logger.debug("Input check: %d observation files in %.2f s", len(files), time.perf_counter() - start)
    return (*version, files)


class _SharedCheck:
    """One check at a time. A caller waits for a check that starts after it arrived (the running one may have read
    the inputs before its change) and every caller waiting for that check takes its result, so a burst of parallel
    requests costs at most two checks and a change finished before a request arrived is always seen."""

    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._running = False
        self._started = self._done = 0
        self._result: tuple = (False, None)

    def __call__(self, fn):
        with self._cv:
            need = self._started + 1
            while self._done < need:
                if not self._running:
                    self._running, self._started = True, self._started + 1
                    mine = self._started
                    break
                self._cv.wait()
            else:
                return self._unwrap(self._result)
        try:
            result = (True, fn())
        except BaseException as exc:  # noqa: BLE001 -- handed to every waiter, then re-raised
            result = (False, exc)
        with self._cv:
            self._running, self._done, self._result = False, mine, result
            self._cv.notify_all()
        return self._unwrap(result)

    @staticmethod
    def _unwrap(result: tuple):
        ok, value = result
        if not ok:
            raise value
        return value


_check = _SharedCheck()
_lock = threading.Lock()
_kept: tuple | None = None  # (version, HouseBuild)
_building: tuple | None = None  # (version, Future) of the build running now


def kept_build(settings, build) -> HouseBuild:
    """The kept build if `input_version` is unchanged, else `build()` (one at a time: a caller with the version being
    built waits for it; one with another version waits for it to end, then builds its own). A build that raises is
    not kept and every caller waiting for it gets its error. Callers must copy the result before changing it."""
    global _kept, _building
    version = _check(lambda: input_version(settings))
    while True:
        with _lock:
            if _kept is not None and _kept[0] == version:
                return _kept[1]
            if _building is None:
                future: Future = Future()
                _building, mine = (version, future), True
            else:
                future, mine = _building[1], None if _building[0] != version else False
        if mine is None:  # another version is being built: wait for it to end, whatever its outcome
            future.exception()
            continue
        if mine is False:
            return future.result()
        try:
            start = time.perf_counter()
            result = build()
            logger.info("House universe built: %d companies in %.2f s", len(result.universe["issuers"]), time.perf_counter() - start)
        except BaseException as exc:
            with _lock:
                _building = None
            future.set_exception(exc)
            raise
        with _lock:
            _kept, _building = (version, result), None
        future.set_result(result)
        return result


def clear_kept_build() -> None:
    """Drops the kept build, so the next call builds (tests)."""
    global _kept
    with _lock:
        _kept = None


def _copy(value):
    """A copy of nested dicts and lists, so no caller changes the kept build (other values are immutable or shared)."""
    if isinstance(value, dict):
        return {k: _copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy(v) for v in value]
    return value


def copy_build(build: HouseBuild) -> HouseBuild:
    return HouseBuild(_copy(build.universe), dict(build.held), build.observations)
