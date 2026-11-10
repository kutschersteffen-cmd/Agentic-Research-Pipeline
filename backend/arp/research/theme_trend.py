"""Theme trend snapshot (spec theme-trend): per theme (taxonomy) and calendar quarter, three point-in-time numbers
from prices and SEC filings (excess return, co-movement, capex / R&D diffusion), stored side by side in one JSON
file per theme. No model call."""

from __future__ import annotations

import csv
import json
import math
import re
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from arp.ingestion.xbrl import CAPEX_TAGS, RND_TAGS, _annual_row
from arp.replication.price_data import PriceDataSource, PricePanel
from arp.research.stock_inference import comove as cm
from arp.research.stock_inference.schemas import InferRun
from arp.storage.atomic_io import atomic_write_text, read_text_utf8
from arp.storage.safe_path import safe_id

WINDOW_WEEKS = 52
MIN_STOCKS = 3
EXCESS_BAND = 0.01
DIFFUSION_BAND = (0.45, 0.55)
_TIERS = {"core", "enabler", "adopter"}
_QUARTER = re.compile(r"^(\d{4})Q([1-4])$")
_HEADER = ("quarter\texcess_return\tmarket\tmean_resid_corr\tcorr_change\tcapex_share\tcapex_change\tcapex\t"
           "rnd_share\trnd_change\trnd")


class TrendRefused(Exception):
    """Nothing was written; `args[0]` is the message for the user."""


def trend_path(portfolios_dir: Path, taxonomy_id: str) -> Path:
    return portfolios_dir / "theme_trends" / f"{safe_id(taxonomy_id, label='taxonomy_id')}.json"


# --- quarters -------------------------------------------------------------------------------------------------

def _parse(text: str) -> tuple[int, int]:
    m = _QUARTER.match(text)
    if not m:
        raise TrendRefused(f"Quarter {text} is not in the form YYYYQn.")
    return int(m[1]), int(m[2])


def _label(year: int, q: int) -> str:
    return f"{year}Q{q}"


def _start(year: int, q: int) -> date:
    return date(year, 3 * q - 2, 1)


def quarter_end(year: int, q: int) -> date:
    return _start(year + (q == 4), q % 4 + 1) - timedelta(days=1)


def _last_friday(on_or_before: date) -> date:
    return on_or_before - timedelta(days=(on_or_before.weekday() - 4) % 7)


def resolve_quarters(quarter: str | None, start: str | None, stop: str | None, today: date) -> list[str]:
    """The quarters to compute, or a refusal (the first four rows of the spec's table, in order)."""
    one, range_ = quarter is not None, start is not None and stop is not None
    if one == range_ or (one and (start or stop)):
        raise TrendRefused("Give --quarter, or --from and --to.")
    first = _parse(start or quarter)
    last = _parse(stop or quarter)
    if stop and first > last:
        raise TrendRefused(f"--from {start} is after --to {stop}.")
    if quarter_end(*last) >= today:
        raise TrendRefused(f"Quarter {_label(*last)} has not ended.")
    out, (y, q) = [], first
    while (y, q) <= last:
        out.append(_label(y, q))
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


# --- inputs ---------------------------------------------------------------------------------------------------

def find_run(run_store, taxonomy_id: str) -> InferRun | None:
    """The first run, in sorted run-id order, whose `taxonomy_id` is the argument."""
    root = Path(run_store.runs_dir)
    for d in sorted(root.iterdir()) if root.exists() else ():
        data = run_store.read_snapshot(d.name, "infer")
        if data and data.get("taxonomy_id") == taxonomy_id:
            return InferRun.model_validate(data)
    return None


def members_of(run: InferRun) -> list[str]:
    return sorted({m.company_id for m in run.mapping if m.tier in _TIERS})


def read_ciks(path: str | Path, members: set[str]) -> dict[str, str]:
    """The optional `cik` column of the symbols file, trimmed, as typed."""
    with Path(path).open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {r["company_id"].strip(): c for r in rows
            if r.get("company_id", "").strip() in members and (c := (r.get("cik") or "").strip())}


def facts_from_dir(facts_dir: Path) -> Callable[[str], dict | None]:
    def load(cik: str) -> dict | None:
        path = facts_dir / f"CIK{cik.zfill(10)}.json"
        return json.loads(read_text_utf8(path)) if path.exists() else None
    return load


class _Fetched(PriceDataSource):
    """The panel fetched once for the whole range, sliced per quarter for `comove`'s own window function."""

    name = "fetched"

    def __init__(self, panel: PricePanel) -> None:
        self.panel = panel

    def get_monthly_returns(self, tickers, start, end):
        raise NotImplementedError

    def get_weekly_returns(self, tickers, start, end):
        p = self.panel
        keep = [i for i, d in enumerate(p.period_ends) if start <= d <= end]
        return PricePanel([p.period_ends[i] for i in keep],
                          {t: [p.returns[t][i] for i in keep] if t in p.returns else [None] * len(keep)
                           for t in tickers}, p.source)


# --- numbers --------------------------------------------------------------------------------------------------

def _r(x):
    return None if x is None else round(float(x), 4)


def _direction(x: float, low: float, high: float) -> str:
    return "up" if x > high else "down" if x < low else "flat"


def _quarter_return(panel: PricePanel, ticker: str, weeks: list[str]) -> float | None:
    at = {d: i for i, d in enumerate(panel.period_ends)}
    series = panel.returns.get(ticker)
    if series is None or any(w not in at or at[w] == 0 or series[at[w]] is None for w in weeks):
        return None
    return math.prod(1 + series[at[w]] for w in weeks) - 1


def _market(panel: PricePanel, symbols: dict[str, str], weeks: list[str]) -> dict:
    out = {"weeks": len(weeks), "stocks": None, "basket_return": None, "acwi_return": None, "excess_return": None,
           "direction": None, "skipped": None}
    acwi = _quarter_return(panel, cm.ACWI, weeks)
    got = [r for s in symbols.values() if (r := _quarter_return(panel, s, weeks)) is not None]
    out["stocks"] = len(got)
    if acwi is None:
        return out | {"skipped": "short_control"}
    if len(got) < MIN_STOCKS:
        return out | {"skipped": "too_few_stocks"}
    basket = sum(got) / len(got)
    excess = basket - acwi
    return out | {"basket_return": _r(basket), "acwi_return": _r(acwi), "excess_return": _r(excess),
                  "direction": _direction(excess, -EXCESS_BAND, EXCESS_BAND)}


def _comovement(source: PriceDataSource, symbols: dict[str, tuple[str, str]], end: date) -> dict:
    out = dict.fromkeys(("stocks", "mean_resid_corr", "null_mean", "null_p95", "p_value", "skipped"))
    out = {"window_weeks": WINDOW_WEEKS, **out}
    tickers = sorted({cm.ACWI} | {s for s, _ in symbols.values()} | {h for _, h in symbols.values()})
    returns, _ = cm._window(source, tickers, end.isoformat(), WINDOW_WEEKS)
    need = math.ceil(2 * WINDOW_WEEKS / 3)
    count = {t: int(np.isfinite(r).sum()) for t, r in returns.items()}
    priced = [c for c, (s, h) in sorted(symbols.items()) if count[s] >= need and count[h] >= need]
    out["stocks"] = len(priced)
    if count[cm.ACWI] < need:
        return out | {"skipped": "short_control"}
    if len(priced) < MIN_STOCKS:
        return out | {"skipped": "too_few_stocks"}
    rows = np.array([cm._residualise(returns[symbols[c][0]], returns[cm.ACWI], returns[symbols[c][1]]) for c in priced])
    t = cm._basket_tests(rows)
    return out | {k: _r(t[k]) for k in ("mean_resid_corr", "null_mean", "null_p95", "p_value")}


def _annual_pair(facts: dict | None, tags: list[str], filed_by: str) -> tuple[float, float] | None:
    """(latest, prior) annual value for the first tag with two distinct period ends filed on or before `filed_by`."""
    us_gaap = (facts or {}).get("facts", {}).get("us-gaap", {})
    for tag in tags:
        units = us_gaap.get(tag, {}).get("units", {})
        rows = units.get("USD") or next(iter(units.values()), [])
        seen = [r for r in rows if _annual_row(r) and (r.get("filed") or "9999") <= filed_by]
        ends = sorted({r["end"] for r in seen}, reverse=True)
        if len(ends) >= 2:
            latest, prior = (max((r for r in seen if r["end"] == e), key=lambda r: r["filed"]) for e in ends[:2])
            return float(latest["val"]), float(prior["val"])
    return None


def _diffusion(facts: dict[str, dict | None], ciks: dict[str, str], tags: list[str], filed_by: str) -> dict:
    pairs = [p for c in sorted(ciks) if (p := _annual_pair(facts.get(ciks[c]), tags, filed_by))]
    rising = sum(latest > prior for latest, prior in pairs)
    out = {"companies": len(pairs), "rising": rising, "share": None, "direction": None, "skipped": None}
    if len(pairs) < MIN_STOCKS:
        return out | {"skipped": "too_few_companies"}
    share = rising / len(pairs)
    return out | {"share": _r(share), "direction": _direction(share, *DIFFUSION_BAND)}


# --- snapshots ------------------------------------------------------------------------------------------------

def build_snapshots(quarters: list[str], *, run: InferRun, taxonomy_version: int, members: list[str],
                    symbols: dict[str, tuple[str, str]], ciks: dict[str, str], prices: PriceDataSource,
                    facts_for: Callable[[str], dict | None]) -> list[dict]:
    """One snapshot per quarter; everything is computed (and may raise) before anything is stored."""
    spans = []
    for label in quarters:
        end = quarter_end(*_parse(label))
        last = _last_friday(end)
        prior = _last_friday(_start(*_parse(label)) - timedelta(days=1))
        spans.append((label, end, last, prior, [(prior + timedelta(weeks=k)).isoformat()
                                                for k in range(1, (last - prior).days // 7 + 1)]))
    tickers = sorted({cm.ACWI} | {s for s, _ in symbols.values()} | {h for _, h in symbols.values()})
    panel = prices.get_weekly_returns(tickers, (spans[0][3] - timedelta(weeks=53)).isoformat(), spans[-1][2].isoformat())
    fetched = _Fetched(panel)
    stock_symbols = {c: s for c, (s, _) in symbols.items()}
    used = {c: ciks[c] for c in symbols if c in ciks}
    facts = {cik: facts_for(cik) for cik in sorted(set(used.values()))}
    member_rows = [{"company_id": c, "symbol": symbols[c][0] if c in symbols else None, "cik": used.get(c),
                    "skipped": None if c in symbols else "no_symbol"} for c in members]
    return [{
        "quarter": label, "quarter_end": end.isoformat(), "run_id": run.run_id, "taxonomy_version": taxonomy_version,
        "membership": "current_mapping", "source": panel.source, "members": member_rows,
        "market": _market(panel, stock_symbols, weeks),
        "comovement": _comovement(fetched, symbols, last),
        "diffusion": {"capex": _diffusion(facts, used, CAPEX_TAGS, end.isoformat()),
                      "rnd": _diffusion(facts, used, RND_TAGS, end.isoformat())},
    } for label, end, last, _prior, weeks in spans]


def load_trend(path: Path) -> dict | None:
    """The stored trend, `None` when there is no file; a file that is not this theme's trend is a refusal."""
    if not path.exists():
        return None
    try:
        data = json.loads(read_text_utf8(path))
        if not isinstance(data, dict) or data.get("taxonomy_id") != path.stem:
            raise ValueError("taxonomy_id does not match the file name")
        return data
    except ValueError as e:
        raise TrendRefused(f"Trend file for {path.stem} is unreadable: {e}.") from None


def store_snapshots(path: Path, taxonomy_id: str, snapshots: list[dict]) -> None:
    """Replaces the stored entry of each quarter given and keeps the others, sorted by quarter; atomic."""
    old = load_trend(path) or {"taxonomy_id": taxonomy_id, "snapshots": []}
    kept = {s["quarter"]: s for s in old["snapshots"]} | {s["quarter"]: s for s in snapshots}
    data = {"taxonomy_id": taxonomy_id, "snapshots": [kept[q] for q in sorted(kept)]}
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(data, indent=2) + "\n")


# --- show -----------------------------------------------------------------------------------------------------

def _cell(v) -> str:
    return "n/a" if v is None else f"{v:.4f}"


def _change(now, before):
    return None if now is None or before is None else now - before


def show_lines(data: dict) -> list[str]:
    """The table: `*_change` is this quarter minus the previous stored quarter, only when that one is the
    calendar quarter just before and both values exist."""
    lines, prev, prev_q = [_HEADER], None, None
    for s in data["snapshots"]:
        year, q = _parse(s["quarter"])
        vals = {"corr": s["comovement"]["mean_resid_corr"], "capex": s["diffusion"]["capex"]["share"],
                "rnd": s["diffusion"]["rnd"]["share"]}
        before = (year - 1, 4) if q == 1 else (year, q - 1)
        base = prev if prev_q == before else None
        lines.append("\t".join([
            s["quarter"], _cell(s["market"]["excess_return"]), s["market"]["direction"] or "n/a",
            _cell(vals["corr"]), _cell(_change(vals["corr"], base and base["corr"])),
            _cell(vals["capex"]), _cell(_change(vals["capex"], base and base["capex"])),
            s["diffusion"]["capex"]["direction"] or "n/a",
            _cell(vals["rnd"]), _cell(_change(vals["rnd"], base and base["rnd"])),
            s["diffusion"]["rnd"]["direction"] or "n/a"]))
        prev, prev_q = vals, (year, q)
    return lines


# --- command --------------------------------------------------------------------------------------------------

def snapshot(taxonomy_id: str, symbols_path: str | Path, quarter: str | None, start: str | None, stop: str | None, *,
             taxonomy_store, run_store, portfolios_dir: Path, prices: PriceDataSource,
             facts_for: Callable[[str], dict | None], today: date) -> list[str]:
    """Computes every quarter, then stores them; any refusal or error raises first and writes nothing."""
    quarters = resolve_quarters(quarter, start, stop, today)
    try:  # `TaxonomyStore.get` creates the directory of an unknown id
        known = (taxonomy_store.taxonomies_dir / safe_id(taxonomy_id, label="taxonomy_id")).is_dir()
    except ValueError:
        known = False
    taxonomy = taxonomy_store.get(taxonomy_id) if known else None
    if taxonomy is None:
        raise TrendRefused(f"Taxonomy {taxonomy_id} not found.")
    run = find_run(run_store, taxonomy_id)
    if run is None:
        raise TrendRefused(f"Taxonomy {taxonomy_id} has no stock mapping; "
                           "trend needs a taxonomy made by 'arp taxonomy infer pick'.")
    members = members_of(run)
    load_trend(trend_path(portfolios_dir, taxonomy_id))  # an unreadable file refuses before any price is fetched
    try:
        symbols = cm._read_symbols(symbols_path, set(members))
    except cm.ComoveRefused as e:
        raise TrendRefused(e.args[0]) from None
    snaps = build_snapshots(quarters, run=run, taxonomy_version=taxonomy.version, members=members, symbols=symbols,
                            ciks=read_ciks(symbols_path, set(members)), prices=prices, facts_for=facts_for)
    store_snapshots(trend_path(portfolios_dir, taxonomy_id), taxonomy_id, snaps)
    return quarters
