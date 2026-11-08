"""Theme co-movement from weekly returns (spec theme-comovement): how strongly each stock moves with a basket's
other stocks once ACWI and its home index are removed. Every number is computed here in numpy; no model call."""

from __future__ import annotations

import csv
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from arp.replication.price_data import PriceDataSource
from arp.research.stock_inference.run import _save, load_run

ACWI = "ACWI"
MIN_LOADING_WEEKS = 52
NW_LAGS = 4
DRAWS = 500
FLAG_T = 2.0
_COLUMNS = ("company_id", "symbol", "home_index")


class ComoveRefused(Exception):
    """Nothing was saved; `args[0]` is the message for the user."""


def default_end(today: date) -> str:
    """The most recent Friday strictly before `today`."""
    back = (today.weekday() - 4) % 7 or 7
    return (today - timedelta(days=back)).isoformat()


def _num(x) -> float | None:
    return None if x is None or not np.isfinite(x) else float(x)


def _corr(a: np.ndarray, b: np.ndarray) -> float | None:
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3 or np.std(a[ok]) == 0 or np.std(b[ok]) == 0:
        return None
    return float(np.corrcoef(a[ok], b[ok])[0, 1])


def _residualise(r: np.ndarray, m: np.ndarray, h: np.ndarray) -> np.ndarray:
    """Residual of OLS r ~ [1, m, h] on weeks where all three exist; NaN elsewhere."""
    ok = np.isfinite(r) & np.isfinite(m) & np.isfinite(h)
    e = np.full_like(r, np.nan)
    if ok.sum() > 3:
        x = np.column_stack([np.ones(ok.sum()), m[ok], h[ok]])
        coef, *_ = np.linalg.lstsq(x, r[ok], rcond=None)
        e[ok] = r[ok] - x @ coef
    return e


def _factor(others: np.ndarray) -> np.ndarray:
    """Mean residual per week over `others` (rows); NaN where fewer than 2 have one."""
    count = np.isfinite(others).sum(axis=0)
    total = np.nansum(others, axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(count >= 2, total / count, np.nan)


def _loading(e: np.ndarray, f: np.ndarray) -> dict:
    """OLS e ~ [1, f] with a Newey-West t (Bartlett kernel, as signal_lab.stats.newey_west_t) and side correlations."""
    ok = np.isfinite(e) & np.isfinite(f)
    n = int(ok.sum())
    keys = ("n_weeks", "beta", "partial_r2", "nw_t", "down_corr", "up_corr", "lag_corr", "lead_corr")
    if n < MIN_LOADING_WEEKS:
        return dict.fromkeys(keys)
    y, x = e[ok], np.column_stack([np.ones(n), f[ok]])
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    u = y - x @ coef
    sst = float(((y - y.mean()) ** 2).sum())
    xu = x * u[:, None]
    s = xu.T @ xu
    for lag in range(1, NW_LAGS + 1):
        g = xu[lag:].T @ xu[:-lag]
        s += (1 - lag / (NW_LAGS + 1)) * (g + g.T)
    bread = np.linalg.pinv(x.T @ x)
    var = (bread @ s @ bread)[1, 1]
    with np.errstate(invalid="ignore"):
        down, up = ok & (f < 0), ok & (f > 0)
    return {
        "n_weeks": n,
        "beta": _num(coef[1]),
        "partial_r2": _num(1 - float(u @ u) / sst) if sst > 0 else None,
        "nw_t": _num(coef[1] / math.sqrt(var)) if var > 0 else None,
        "down_corr": _corr(e[down], f[down]),
        "up_corr": _corr(e[up], f[up]),
        "lag_corr": _corr(e[1:], f[:-1]),
        "lead_corr": _corr(e[:-1], f[1:]),
    }


def _mean_corr(rows: np.ndarray) -> float | None:
    """Mean Pearson correlation over all row pairs, each pair on its shared weeks (as `_corr`, vectorised)."""
    m = np.isfinite(rows).astype(float)
    z = np.where(m > 0, rows, 0.0)
    n = m @ m.T
    with np.errstate(invalid="ignore", divide="ignore"):
        sx = z @ m.T  # sx[i, j]: sum of row i over weeks shared with row j
        cov = z @ z.T - sx * sx.T / n
        var = (z * z) @ m.T - sx * sx / n
        r = cov / np.sqrt(var * var.T)
    pair = np.triu(np.ones_like(n, dtype=bool), 1) & (n >= 3) & (np.minimum(var, var.T) > 1e-12 * n)
    vals = r[pair]
    return float(vals.mean()) if vals.size else None


def _shuffle(rows: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Each row's observed values permuted among that row's observed weeks; gaps stay put."""
    out = rows.copy()
    for row in out:
        obs = np.isfinite(row)
        row[obs] = rng.permutation(row[obs])
    return out


def _eigen(rows: np.ndarray) -> tuple[int, list[float] | None, float | None, int | None]:
    """(complete_weeks, top-5 eigenvalues, Marchenko-Pastur lambda+, count above it); None when T < 2N."""
    complete = np.isfinite(rows).all(axis=0)
    t, n = int(complete.sum()), len(rows)
    if t < 2 * n:
        return t, None, None, None
    corr = np.corrcoef(rows[:, complete])
    if not np.isfinite(corr).all():  # a member with a constant residual on the complete weeks
        return t, None, None, None
    eig = sorted(np.linalg.eigvalsh(corr).tolist(), reverse=True)
    mp = (1 + math.sqrt(n / t)) ** 2
    return t, eig[:5], mp, sum(v > mp for v in eig)


def _basket_tests(rows: np.ndarray) -> dict:
    observed = _mean_corr(rows)
    rng = np.random.default_rng(0)
    draws = [d for _ in range(DRAWS) if (d := _mean_corr(_shuffle(rows, rng))) is not None]
    t, eig, mp, above = _eigen(rows)
    nulls = observed is None or not draws
    return {
        "mean_resid_corr": observed,
        "null_mean": None if nulls else float(np.mean(draws)),
        "null_p95": None if nulls else float(np.percentile(draws, 95)),
        "p_value": None if nulls else (1 + sum(d >= observed for d in draws)) / (len(draws) + 1),
        "complete_weeks": t, "eigenvalues": eig, "mp_lambda_plus": mp, "factors_above_noise": above,
    }


def _read_symbols(path: str | Path, described: set[str]) -> dict[str, tuple[str, str]]:
    with Path(path).open(newline="") as fh:
        reader = csv.DictReader(fh)
        if not set(_COLUMNS) <= set(reader.fieldnames or []):
            raise ComoveRefused(f"{path}: needs columns company_id, symbol, home_index.")
        rows = [{k: (r.get(k) or "").strip() for k in _COLUMNS} for r in reader]
    kept: dict[str, tuple[str, str]] = {}
    for r in sorted((r for r in rows if r["company_id"] in described and r["symbol"]), key=lambda r: r["company_id"]):
        if r["company_id"] in kept:
            raise ComoveRefused(f"{path}: company_id {r['company_id']} appears twice.")
        kept[r["company_id"]] = (r["symbol"], r["home_index"])
    for cid, (_, home) in kept.items():
        if not home:
            raise ComoveRefused(f"Stock {cid} has no home_index.")
    stock_symbols = {s for s, _ in kept.values()}
    for _, (symbol, home) in kept.items():
        if symbol == ACWI:
            raise ComoveRefused(f"Control {ACWI} is also a stock in the run.")
        if home in stock_symbols:
            raise ComoveRefused(f"Control {home} is also a stock in the run.")
    return kept


def _window(prices: PriceDataSource, tickers: list[str], end: str, weeks: int) -> tuple[dict[str, np.ndarray], str]:
    start = (date.fromisoformat(end) - timedelta(weeks=weeks)).isoformat()
    panel = prices.get_weekly_returns(tickers, start, end)
    keep = [i for i, d in enumerate(panel.period_ends) if d <= end][-weeks:]
    keep = [i for i in keep if i > 0]  # index 0 has no prior week to return from
    out = {t: np.array([panel.returns.get(t, [None] * len(panel.period_ends))[i] for i in keep], dtype=float)
           for t in tickers}
    return out, panel.source


def comove(run_id: str, symbols_path: str | Path, prices: PriceDataSource, end: str, weeks: int, run_store) -> dict:
    """Compute and store the run's `comovement` block; a refusal raises before anything is saved."""
    run = load_run(run_id, run_store)
    if run.stage not in ("themes_ready", "drafted"):
        raise ComoveRefused(f"Run {run_id} is at stage '{run.stage}'; 'comove' needs 'themes_ready' or 'drafted'.")
    described = sorted(p.company_id for p in run.profiles if p.description)
    symbols = _read_symbols(symbols_path, set(described))
    tickers = sorted({ACWI} | {s for s, _ in symbols.values()} | {h for _, h in symbols.values()})
    returns, source = _window(prices, tickers, end, weeks)
    need = math.ceil(2 * weeks / 3)
    count = {t: int(np.isfinite(r).sum()) for t, r in returns.items()}
    if count[ACWI] < need:
        raise ComoveRefused(f"Control {ACWI} has prices for only {count[ACWI]} of {weeks} weeks.")

    stocks = []
    for cid in described:
        symbol, home = symbols.get(cid, (None, None))
        n = count[symbol] if symbol else None
        skipped = ("no_symbol" if symbol is None else "short_history" if n < need
                   else "short_control" if count[home] < need else None)
        stocks.append({"company_id": cid, "symbol": symbol, "home_index": home, "n_returns": n, "skipped": skipped})
    priced = [s["company_id"] for s in stocks if s["skipped"] is None]
    if len(priced) < 3:
        raise ComoveRefused(f"Only {len(priced)} stocks have prices for at least {need} of {weeks} weeks; comove needs 3.")

    resid = {cid: _residualise(returns[symbols[cid][0]], returns[ACWI], returns[symbols[cid][1]]) for cid in priced}
    baskets_in = [("all", priced)] + [(f"theme:{t.rank}", sorted(set(t.supporting) & set(priced)))
                                      for t in sorted(run.themes, key=lambda t: t.rank)]
    baskets, loadings = [], []
    for name, members in baskets_in:
        if len(members) < 3:
            baskets.append({"basket": name, "members": members, "skipped": "too_few_stocks",
                            **dict.fromkeys(("mean_resid_corr", "null_mean", "null_p95", "p_value", "complete_weeks",
                                             "eigenvalues", "mp_lambda_plus", "factors_above_noise"))})
            continue
        rows = np.array([resid[m] for m in members])
        baskets.append({"basket": name, "members": members, "skipped": None, **_basket_tests(rows)})
        outside = _factor(rows)  # a non-member's factor is the mean over all members
        for cid in priced:
            member = cid in members
            f = _factor(np.delete(rows, members.index(cid), axis=0)) if member else outside
            row = _loading(resid[cid], f)
            flag = None
            if name != "all" and row["nw_t"] is not None:
                flag = ("text_only" if member and row["nw_t"] < FLAG_T
                        else "returns_only" if not member and row["nw_t"] >= FLAG_T else None)
            loadings.append({"basket": name, "company_id": cid, "member": member, **row, "flag": flag})

    block = {"end": end, "weeks": weeks, "source": source, "controls": [ACWI, "home_index"],
             "stocks": stocks, "baskets": baskets, "loadings": loadings}
    fresh = load_run(run_id, run_store)  # reloaded: a `pick` that saved during a slow price fetch is kept
    _save(fresh.model_copy(update={"comovement": block}), run_store)
    return block
