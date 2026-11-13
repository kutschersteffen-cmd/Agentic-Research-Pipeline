"""`arp showcase load`: the seven public holdings files and the SIMULATED ESG dataset into Transition Intelligence
(spec `showcase-portfolio-data`, PR 2).

SIMULATED DATA. The holdings of June to October 2026 and every ESG value written here are invented and say so:
observations carry source `simulated`, load records `simulated` in their detail, portfolios the tag
`history:simulated`. Every draw is seeded from SHA-256, so a second run changes nothing.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Callable
from pathlib import Path

from arp.bi.published import month_end
from arp.config import Settings
from arp.portfolio.climate.esg_intake import FIELD_IDS as CLIMATE_FIELD_IDS
from arp.portfolio.climate.schemas import FIELD_CARBON_INTENSITY, FIELD_SCOPE1, FIELD_SCOPE2, build_climate_schema
from arp.portfolio.constituent_import import import_holdings_files
from arp.portfolio.loads import LoadRecord, latest_load, record_load
from arp.portfolio.monthly_run import run_month
from arp.schemas.datapoints import FieldDataType
from arp.schemas.portfolio import DataPointObservation, Portfolio
from arp.showcase.schema import build_simulated_schema
from arp.showcase.simulate import FILE_ORDER, _draw

MONTHS = ("2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11")
DATASET_DATE = "2026-11-02"  # the dataset is the 2026-11 load; earlier months are observed at their month end
FUND_ISIN = {"AI_Big_Data": "IE00BGV5VN51"}  # the only file that is a fund with an ISIN
# Emissions fall over time: month m's value = the dataset's x (1 + g x months before 2026-11), g by transition grade.
_DRIFT = {"A": 0.010, "B": 0.008, "C": 0.006, "D": 0.004, "E": 0.002, "F": 0.0}
_DRIFTING = (FIELD_SCOPE1, FIELD_SCOPE2, FIELD_CARBON_INTENSITY)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_once(store, rec: LoadRecord) -> None:
    last = latest_load(store, rec.kind, rec.source_id, rec.month)
    if last is None or (last.status, last.content_hash) != (rec.status, rec.content_hash):
        record_load(store, rec)


def _append_new(store, company_id: str, field_id: str, new: list[DataPointObservation]) -> int:
    """Appends the observations not stored yet (same source, period and value), so a re-run adds nothing."""
    have = {(o.source, o.period, o.value) for o in store.load_observations(company_id, field_id)}
    fresh = [o for o in new if (o.source, o.period, o.value) not in have]
    for obs in fresh:
        store.append_observation(obs)
    return len(fresh)


def _import(store, holdings_dir: Path) -> list[tuple[Path, dict]]:
    imported = []
    for stem in FILE_ORDER:
        path = holdings_dir / f"{stem}.xlsx"
        summary = import_holdings_files(store, [path], fund_isin=FUND_ISIN.get(stem))
        imported.append((path, summary["portfolios"][0]))
    return imported


def _history(store, imported: list[tuple[Path, dict]]) -> int:
    """A snapshot per earlier month end: the file's securities, each weight moved by up to 5 % either way and
    the month rescaled to the file's weight sum. Returns the number of snapshots written."""
    written = 0
    for path, summary in imported:
        portfolio_id, file_date = summary["portfolio_id"], summary["as_of_date"]
        base = store.load_snapshot(portfolio_id, file_date)
        total = sum(h.weight_pct for h in base)
        digest = _sha256(path)
        for month in MONTHS:
            end = month_end(month)
            if end >= file_date:
                continue
            factors = [1 + _draw(f"{portfolio_id}|{h.security_id}|{month}", "weight", -0.05, 0.05) for h in base]
            scale = total / sum(h.weight_pct * f for h, f in zip(base, factors, strict=True))
            store.save_snapshot(portfolio_id, end, [
                h.model_copy(update={
                    "as_of_date": end, "quantity": h.quantity * f * scale, "market_value": h.market_value * f * scale,
                    "market_value_eur": h.market_value_eur * f * scale, "weight_pct": h.weight_pct * f * scale,
                })
                for h, f in zip(base, factors, strict=True)
            ])
            _record_once(store, LoadRecord(kind="holdings", source_id=portfolio_id, month=month, status="ok",
                                           content_hash=digest, detail=f"simulated history from {path.name}"))
            written += 1
        portfolio = store.get_portfolio(portfolio_id)
        if "history:simulated" not in portfolio.tags:
            store.save_portfolio(Portfolio(portfolio_id=portfolio_id, name=portfolio.name, tags=[*portfolio.tags, "history:simulated"]))
    return written


def _esg(store, rows: list[dict], dataset: Path) -> int:
    """The seven climate values per company and month, then the month's `simulated` ESG load."""
    fields = {f.field_id: f for f in build_climate_schema().fields}
    days = {m: DATASET_DATE if m == MONTHS[-1] else month_end(m) for m in MONTHS}
    written = 0
    for row in rows:
        drift = _DRIFT[row["transition_grade"]]
        for fid in CLIMATE_FIELD_IDS:
            value = float(row[fid])
            written += _append_new(store, row["company_id"], fid, [
                DataPointObservation(
                    company_id=row["company_id"], field_id=fid, field_name=fields[fid].name, unit=fields[fid].unit,
                    value=round(value * (1 + drift * (len(MONTHS) - 1 - k)), 6) if fid in _DRIFTING else value,
                    period=month, observed_at=f"{days[month]}T00:00:00+00:00", source="simulated",
                    notes=f"simulated: {dataset.name}",
                )
                for k, month in enumerate(MONTHS)
            ])
    digest = _sha256(dataset)
    for month in MONTHS:
        _record_once(store, LoadRecord(kind="esg", source_id="simulated", month=month, status="ok", content_hash=digest,
                                       at=f"{days[month]}T00:00:00+00:00", detail=f"simulated ESG from {dataset.name}"))
    return written


def _scores(store, rows: list[dict], dataset: Path) -> int:
    """The 25 `simulated_esg` fields per company, for 2026-11."""
    written = 0
    for field in build_simulated_schema().fields:
        column = "sector" if field.field_id == "peer_group" else field.field_id
        for row in rows:
            cell = row[column]
            if field.data_type == FieldDataType.NUMBER:
                value: float | bool | str = float(cell)
            elif field.data_type == FieldDataType.BOOLEAN:
                value = cell == "true"
            else:
                value = cell
            written += _append_new(store, row["company_id"], field.field_id, [
                DataPointObservation(
                    company_id=row["company_id"], field_id=field.field_id, field_name=field.name, unit=field.unit, value=value,
                    period=MONTHS[-1], observed_at=f"{DATASET_DATE}T00:00:00+00:00", source="simulated",
                    notes=f"simulated: {dataset.name}",
                )
            ])
    return written


def load(store, settings: Settings, holdings_dir: Path, dataset: Path, echo: Callable[[str], None] = print) -> bool:
    """Runs the five steps, printing `ok|FAIL <step>: <reason>` for each. False on the first FAIL; later steps
    build on earlier ones, so they are not attempted."""
    state: dict = {}

    def read_dataset() -> list[dict]:
        if "rows" not in state:
            with dataset.open(newline="", encoding="utf-8") as fh:
                state["rows"] = list(csv.DictReader(fh))
            if not state["rows"]:
                raise ValueError(f"{dataset.name}: no data rows")
        return state["rows"]

    def step_import() -> str:
        state["imported"] = _import(store, holdings_dir)
        return f"{len(state['imported'])} portfolios, {sum(s['holdings_written'] for _, s in state['imported'])} holdings"

    steps: list[tuple[str, Callable[[], str]]] = [
        ("import", step_import),
        ("history", lambda: f"{_history(store, state['imported'])} simulated month-end snapshots"),
        ("esg", lambda: f"{_esg(store, read_dataset(), dataset)} new simulated climate observations, {len(MONTHS)} months"),
        ("scores", lambda: f"{_scores(store, read_dataset(), dataset)} new simulated score observations"),
    ]
    for name, step in steps:
        try:
            echo(f"ok {name}: {step()}")
        except Exception as exc:  # any failure is this step's FAIL line, not a traceback
            echo(f"FAIL {name}: {exc}")
            return False
    portfolio_ids = [s["portfolio_id"] for _, s in state["imported"]]
    for month in MONTHS:
        try:
            result = run_month(store, settings, month, portfolio_ids=portfolio_ids, esg_provider="simulated")
        except Exception as exc:
            echo(f"FAIL run {month}: {exc}")
            return False
        if result.status != "ran":
            echo(f"FAIL run {month}: {'; '.join(result.blocked_reasons)}")
            return False
        echo(f"ok run {month}: {result.alerts} alerts, {result.triggers} triggers")
    return True
