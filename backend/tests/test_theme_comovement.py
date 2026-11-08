"""Spec theme-comovement: `arp taxonomy infer comove`, on the Acceptance section's fixture."""

import json
import sys
import types
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from arp.cli import taxonomy as taxonomy_cli
from arp.cli import taxonomy_infer as cli
from arp.config import get_settings
from arp.db.runs import RunStore
from arp.replication.price_data import CsvPriceSource, YFinancePriceSource
from arp.research.stock_inference import comove as comove_mod
from arp.research.stock_inference.run import dump
from arp.research.stock_inference.schemas import InferRun, Selection, StockProfile, Theme

END = "2026-10-30"
COLS = ["ACWI", "HOME1", "HOME2", "A1", "A2", "A3", "A4", "B1", "B2"]


def _fixture_columns():
    rng = np.random.default_rng(0)
    m, h1, h2 = (rng.normal(0.0, 0.02, 159) for _ in range(3))
    t = rng.normal(0.0, 0.03, 159)
    a = [rng.normal(0.0, 0.02, 159) for _ in range(4)]
    b = [rng.normal(0.0, 0.03, 159) for _ in range(2)]
    rets = {"ACWI": m, "HOME1": h1, "HOME2": h2}
    rets |= {f"A{i + 1}": m + h1 + t + n for i, n in enumerate(a)}
    rets |= {f"B{i + 1}": m + h2 + n for i, n in enumerate(b)}
    prices = {k: np.concatenate([[100.0], 100.0 * np.cumprod(1 + r)]) for k, r in rets.items()}
    dates = [(date(2026, 10, 30) - timedelta(weeks=159 - i)).isoformat() for i in range(160)]
    return dates, prices, m


def _write_prices(path, blank=None, drop=()):
    dates, prices, _ = _fixture_columns()
    cols = [c for c in COLS if c not in drop]
    lines = ["date," + ",".join(cols)]
    for i, d in enumerate(dates):
        cells = ["" if blank and c in blank and i < blank[c] else repr(float(prices[c][i])) for c in cols]
        lines.append(d + "," + ",".join(cells))
    path.write_text("\n".join(lines) + "\n")
    return path


SYMBOLS = {"a1": ("A1", "HOME1"), "a2": ("A2", "HOME1"), "a3": ("A3", "HOME1"), "a4": ("A4", "HOME1"),
           "b1": ("B1", "HOME2"), "b2": ("B2", "HOME2")}


def _write_symbols(path, rows=None):
    rows = list(SYMBOLS.items()) if rows is None else rows
    path.write_text("company_id,symbol,home_index\n" + "".join(f"{c},{s},{h}\n" for c, (s, h) in rows))
    return path


def _run(run_id, stage="themes_ready", themes=None):
    profiles = [StockProfile(company_id=c, name=c.upper(), description=f"{c} makes things") for c in SYMBOLS]
    themes = themes or [Theme(rank=1, name="Hydrogen", description="H2", supporting=["a1", "a2", "a3", "b1"],
                              count_share=0.67)]
    return InferRun(run_id=run_id, stage=stage, name="fund", extractor_model="m", verifier_model="v",
                    selection=Selection(method="sample", cutoff_reason="all"), profiles=profiles, themes=themes)


@pytest.fixture
def fx(pg, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_run_store", lambda: RunStore(pg, tmp_path / "runs"))

    class Fx:
        store = RunStore(pg, tmp_path / "runs")
        prices = _write_prices(tmp_path / "prices.csv")
        symbols = _write_symbols(tmp_path / "symbols.csv")

        def save(self, run):
            self.store.save_snapshot(run.run_id, "infer", dump(run))
            return run.run_id

        def raw(self, run_id):
            return json.dumps(self.store.read_snapshot(run_id, "infer"), sort_keys=True)

    return Fx()


def _invoke(*args):
    return CliRunner().invoke(taxonomy_cli.taxonomy_app, ["infer", *args])


def _comove(run_id, symbols, prices, *extra):
    return _invoke("comove", run_id, "--symbols", str(symbols), "--prices", str(prices), "--end", END, *extra)


def _show(run_id):
    res = _invoke("show", run_id, "--json")
    assert res.exit_code == 0, res.output
    return json.loads(res.stdout)


def _loading(block, basket, cid):
    return next(r for r in block["loadings"] if r["basket"] == basket and r["company_id"] == cid)


@pytest.fixture
def done(fx):
    run_id = fx.save(_run("r1"))
    before = _show(run_id)
    res = _comove(run_id, fx.symbols, fx.prices)
    assert res.exit_code == 0, res.output
    return run_id, res, before, _show(run_id)


# --- the happy path (AC-1 .. AC-13, AC-33, AC-40, AC-41) ---

def test_ac1_ac2_ac13_run_line_stage_and_window(done):
    run_id, res, _, after = done
    assert res.stdout.splitlines()[0] == f"Run {run_id}"
    assert after["stage"] == "themes_ready"
    c = after["comovement"]
    assert (c["end"], c["weeks"], c["source"], c["controls"]) == (END, 156, "csv", ["ACWI", "home_index"])


def test_ac3_ac4_ac5_baskets_and_loadings(done):
    c = done[3]["comovement"]
    assert [b["basket"] for b in c["baskets"]] == ["all", "theme:1"]
    assert c["baskets"][1]["members"] == ["a1", "a2", "a3", "b1"]
    assert len(c["loadings"]) == 12
    assert {r["company_id"]: r["member"] for r in c["loadings"] if r["basket"] == "theme:1"} == {
        "a1": True, "a2": True, "a3": True, "b1": True, "a4": False, "b2": False}


def test_ac6_to_ac10_flags(done):
    c = done[3]["comovement"]
    for cid in ("a1", "a2", "a3"):
        r = _loading(c, "theme:1", cid)
        assert r["nw_t"] > 5 and r["partial_r2"] > 0.3 and r["flag"] is None
    assert _loading(c, "theme:1", "b1")["flag"] == "text_only"
    assert _loading(c, "theme:1", "a4")["flag"] == "returns_only"
    assert _loading(c, "theme:1", "b2")["flag"] is None
    assert all(r["flag"] is None for r in c["loadings"] if r["basket"] == "all")


def test_ac11_ac12_basket_tests(done):
    all_, theme = done[3]["comovement"]["baskets"]
    assert all_["mean_resid_corr"] > all_["null_p95"] and all_["p_value"] == 0.002
    assert theme["complete_weeks"] == 156 and theme["mp_lambda_plus"] == 1.3459
    assert theme["factors_above_noise"] == 1
    assert len(theme["eigenvalues"]) == 4 and theme["eigenvalues"] == sorted(theme["eigenvalues"], reverse=True)


def test_ac33_other_keys_unchanged(done):
    _, _, before, after = done
    assert {k: v for k, v in after.items() if k != "comovement"} == before


def test_ac40_ac41_stdout_tables(done):
    lines = done[1].stdout.splitlines()
    assert lines[1] == "basket\tmembers\tmean_resid_corr\tnull_p95\tp_value\tfactors_above_noise"
    assert lines[2].startswith("all\t6\t") and lines[3].startswith("theme:1\t4\t")
    assert lines[4] == "flag\tbasket\tcompany_id\tnw_t"
    assert len(lines) == 7
    assert lines[5].startswith("returns_only\ttheme:1\ta4\t") and lines[6].startswith("text_only\ttheme:1\tb1\t")


# --- inputs ---

def test_ac14_row_order_does_not_matter(fx, tmp_path):
    a, b = fx.save(_run("r1")), fx.save(_run("r2"))
    rev = _write_symbols(tmp_path / "rev.csv", list(SYMBOLS.items())[::-1])
    assert _comove(a, fx.symbols, fx.prices).exit_code == 0
    assert _comove(b, rev, fx.prices).exit_code == 0
    assert _show(a)["comovement"] == _show(b)["comovement"]


def _stock(block, cid):
    return next(s for s in block["stocks"] if s["company_id"] == cid)


def test_ac15_ac16_no_symbol(fx, tmp_path):
    run_id = fx.save(_run("r1"))
    sym = _write_symbols(tmp_path / "s.csv", [r for r in SYMBOLS.items() if r[0] != "b2"])
    assert _comove(run_id, sym, fx.prices).exit_code == 0
    c = _show(run_id)["comovement"]
    assert _stock(c, "b2")["skipped"] == "no_symbol"
    assert not any(r["company_id"] == "b2" for r in c["loadings"])


def test_ac17_short_history(fx, tmp_path):
    run_id = fx.save(_run("r1"))
    assert _comove(run_id, fx.symbols, _write_prices(tmp_path / "p.csv", blank={"A4": 60})).exit_code == 0
    s = _stock(_show(run_id)["comovement"], "a4")
    assert (s["skipped"], s["n_returns"]) == ("short_history", 99)


def test_ac18_missing_column(fx, tmp_path):
    run_id = fx.save(_run("r1"))
    assert _comove(run_id, fx.symbols, _write_prices(tmp_path / "p.csv", drop=("B2",))).exit_code == 0
    s = _stock(_show(run_id)["comovement"], "b2")
    assert (s["skipped"], s["n_returns"]) == ("short_history", 0)


def test_ac19_short_control(fx, tmp_path):
    run_id = fx.save(_run("r1"))
    assert _comove(run_id, fx.symbols, _write_prices(tmp_path / "p.csv", blank={"HOME2": 160})).exit_code == 0
    c = _show(run_id)["comovement"]
    assert _stock(c, "b1")["skipped"] == _stock(c, "b2")["skipped"] == "short_control"


def test_ac19a_partly_short_control_is_enough(fx, tmp_path):
    run_id = fx.save(_run("r1"))
    assert _comove(run_id, fx.symbols, _write_prices(tmp_path / "p.csv", blank={"HOME2": 50})).exit_code == 0
    c = _show(run_id)["comovement"]
    assert _stock(c, "b1")["skipped"] is None and _stock(c, "b2")["skipped"] is None


def test_ac20_ac21_small_theme_skipped(fx):
    themes = [Theme(rank=1, name="H", description="H", supporting=["a1", "a2", "a3", "b1"], count_share=0.67),
              Theme(rank=2, name="B", description="B", supporting=["b1", "b2"], count_share=0.33)]
    run_id = fx.save(_run("r1", themes=themes))
    assert _comove(run_id, fx.symbols, fx.prices).exit_code == 0
    c = _show(run_id)["comovement"]
    t2 = c["baskets"][2]
    assert (t2["basket"], t2["skipped"], t2["mean_resid_corr"]) == ("theme:2", "too_few_stocks", None)
    assert not any(r["basket"] == "theme:2" for r in c["loadings"])


# --- refusals: exact message, run untouched ---

def _refused(fx, run_id, res, message):
    assert res.exit_code == 1
    assert res.stderr.strip() == message


@pytest.mark.parametrize("rows,message", [
    ({"b1": ("B1", "A1")}, "Control A1 is also a stock in the run."),
    ({"a1": ("ACWI", "HOME1")}, "Control ACWI is also a stock in the run."),
    ({"a3": ("A3", "")}, "Stock a3 has no home_index."),
])
def test_ac22_ac23_ac27_symbol_refusals(fx, tmp_path, rows, message):
    run_id = fx.save(_run("r1"))
    before = fx.raw(run_id)
    sym = _write_symbols(tmp_path / "s.csv", list({**SYMBOLS, **rows}.items()))
    _refused(fx, run_id, _comove(run_id, sym, fx.prices), message)
    assert fx.raw(run_id) == before


def test_ac24_short_acwi(fx, tmp_path):
    run_id = fx.save(_run("r1"))
    before = fx.raw(run_id)
    prices = _write_prices(tmp_path / "p.csv", blank={"ACWI": 160})
    _refused(fx, run_id, _comove(run_id, fx.symbols, prices), "Control ACWI has prices for only 0 of 156 weeks.")
    assert fx.raw(run_id) == before


def test_ac25_too_few_priced(fx, tmp_path):
    run_id = fx.save(_run("r1"))
    before = fx.raw(run_id)
    sym = _write_symbols(tmp_path / "s.csv", [r for r in SYMBOLS.items() if r[0] in ("a1", "a2")])
    _refused(fx, run_id, _comove(run_id, sym, fx.prices),
             "Only 2 stocks have prices for at least 104 of 156 weeks; comove needs 3.")
    assert fx.raw(run_id) == before


def test_ac26_bad_columns(fx, tmp_path, monkeypatch):
    run_id = fx.save(_run("r1"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "bad.csv").write_text("company_id,ticker\na1,A1\n")
    _refused(fx, run_id, _comove(run_id, "bad.csv", fx.prices), "bad.csv: needs columns company_id, symbol, home_index.")


def test_ac28_duplicate_row(fx, tmp_path, monkeypatch):
    run_id = fx.save(_run("r1"))
    monkeypatch.chdir(tmp_path)
    _write_symbols(tmp_path / "sym.csv", [*SYMBOLS.items(), ("a3", SYMBOLS["a3"])])
    _refused(fx, run_id, _comove(run_id, "sym.csv", fx.prices), "sym.csv: company_id a3 appears twice.")


def test_unknown_ids_are_ignored_before_checks(fx, tmp_path):
    run_id = fx.save(_run("r1"))
    sym = _write_symbols(tmp_path / "s.csv", [*SYMBOLS.items(), ("zz", ("A1", "")), ("zz", ("ACWI", "A2"))])
    assert _comove(run_id, sym, fx.prices).exit_code == 0


def test_ac29_wrong_stage(fx):
    run_id = fx.save(_run("r1", stage="failed"))
    _refused(fx, run_id, _comove(run_id, fx.symbols, fx.prices),
             f"Run {run_id} is at stage 'failed'; 'comove' needs 'themes_ready' or 'drafted'.")


def test_ac30_unknown_run(fx):
    _refused(fx, "nope", _comove("nope", fx.symbols, fx.prices), "Run nope not found.")


# --- re-run, untouched runs, stages ---

def test_ac31_rerun_replaces_block(fx):
    run_id = fx.save(_run("r1"))
    assert _comove(run_id, fx.symbols, fx.prices).exit_code == 0
    res = _comove(run_id, fx.symbols, fx.prices, "--weeks", "120")
    assert res.exit_code == 0, res.output
    assert _show(run_id)["comovement"]["weeks"] == 120


def test_ac32_show_without_comove_equals_dump(fx):
    run = _run("r1")
    run_id = fx.save(run)
    shown = _show(run_id)
    assert "comovement" not in shown and shown == dump(run)


def test_ac34_drafted_stays_drafted(fx):
    run_id = fx.save(_run("r1", stage="drafted"))
    assert _comove(run_id, fx.symbols, fx.prices).exit_code == 0
    assert _show(run_id)["stage"] == "drafted"


def test_ac42_no_llm_key(fx, monkeypatch, done):
    monkeypatch.delenv("ARP_ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    run_id = fx.save(_run("r9"))
    assert _comove(run_id, fx.symbols, fx.prices).exit_code == 0
    assert _show(run_id)["comovement"] == done[3]["comovement"]


@pytest.mark.asyncio
async def test_ac43_pick_keeps_block(pg, tmp_path):
    from arp.config import Settings
    from arp.ingestion.registry import DocumentSourceRegistry
    from arp.orchestration.job_manager import JobManager
    from arp.research.stock_inference import pick as pick_mod
    from arp.research.stock_inference.run import load_run
    from arp.storage.taxonomy_store import TaxonomyStore
    from tests.test_stock_inference_pick import fake_steps
    from tests.test_stock_inference_profile import _doc, _FixedDocSource

    store = RunStore(pg, tmp_path / "runs")
    run_id = JobManager(store).create_run("stock_inference", {"methodology": [], "segments": None}, 6).run_id
    store.save_snapshot(run_id, "infer", dump(_run(run_id)))
    comove_mod.comove(run_id, _write_symbols(tmp_path / "s.csv"), CsvPriceSource(_write_prices(tmp_path / "p.csv")),
                      END, 156, store)
    block = load_run(run_id, store).comovement
    source = _FixedDocSource({c: [_doc(f"D{c}", c)] for c in SYMBOLS})
    run = await pick_mod.pick(run_id, 1, run_store=store, taxonomy_store=TaxonomyStore(tmp_path / "tax"),
                              settings=Settings(anthropic_api_key="x"), llm=None,
                              registry=DocumentSourceRegistry([source]), **fake_steps())
    assert block is not None and run.stage == "drafted"
    assert load_run(run_id, store).comovement == block


# --- price sources (AC-35 .. AC-38) and the default end (AC-39) ---

def test_ac35_ac36_weekly_and_monthly_csv(tmp_path):
    path = _write_prices(tmp_path / "p.csv")
    _, _, m = _fixture_columns()
    src = CsvPriceSource(path)
    for panel in (src.get_weekly_returns(["ACWI"], "2023-01-01", END), src.get_monthly_returns(["ACWI"], "2023-01-01", END)):
        assert len(panel.period_ends) == 160 and panel.period_ends[-1] == END
        assert panel.returns["ACWI"][0] is None
        assert panel.returns["ACWI"][1] == pytest.approx(m[0], abs=1e-9)


def test_ac37_monthly_missing_column_still_raises(tmp_path):
    with pytest.raises(ValueError):
        CsvPriceSource(_write_prices(tmp_path / "p.csv")).get_monthly_returns(["NOPE"], "2023-01-01", END)


def test_weekly_missing_column_is_all_none(tmp_path):
    panel = CsvPriceSource(_write_prices(tmp_path / "p.csv")).get_weekly_returns(["NOPE"], "2026-10-01", END)
    assert panel.returns["NOPE"] == [None] * len(panel.period_ends)


def test_ac38_yfinance_weekly(monkeypatch):
    days = pd.bdate_range("2026-10-19", "2026-10-30")
    closes = [100.0 if d.isoformat()[:10] == "2026-10-23" else 110.0 if d.isoformat()[:10] == "2026-10-30" else 99.0
              for d in days]
    frame = pd.DataFrame({"Close": closes}, index=days)
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(download=lambda *a, **k: frame))
    panel = YFinancePriceSource().get_weekly_returns(["X"], "2026-10-19", END)
    assert panel.period_ends == ["2026-10-23", "2026-10-30"]
    assert panel.returns["X"][1] == pytest.approx(0.1, abs=1e-9)


def test_ac39_default_end():
    assert comove_mod.default_end(date(2026, 11, 6)) == "2026-10-30"
    assert comove_mod.default_end(date(2026, 11, 7)) == "2026-11-06"


# --- method pieces with known answers ---

def test_shuffle_keeps_gaps_in_place():
    e = np.array([[1.0, np.nan, 3.0, 4.0], [np.nan, 2.0, 5.0, 1.0]])
    out = comove_mod._shuffle(e, np.random.default_rng(0))
    assert np.array_equal(np.isnan(out), np.isnan(e))
    assert sorted(out[0][~np.isnan(out[0])]) == [1.0, 3.0, 4.0]


def test_eigenvalues_need_twice_as_many_weeks_as_members():
    rng = np.random.default_rng(1)
    short = comove_mod._eigen(rng.normal(size=(5, 9)))
    assert short == (9, None, None, None)
    weeks, eig, mp, above = comove_mod._eigen(rng.normal(size=(3, 10)))
    assert weeks == 10 and len(eig) == 3 and mp == pytest.approx((1 + np.sqrt(3 / 10)) ** 2)


def test_loading_on_a_perfect_factor():
    rng = np.random.default_rng(2)
    f = rng.normal(size=80)
    row = comove_mod._loading(2 * f, f)
    assert row["n_weeks"] == 80 and row["beta"] == pytest.approx(2) and row["partial_r2"] == pytest.approx(1)


def test_loading_below_52_weeks_is_all_null():
    f = np.arange(60, dtype=float)
    f[:10] = np.nan
    row = comove_mod._loading(np.sin(np.arange(60.0)), np.where(np.arange(60) < 20, np.nan, f))
    assert all(v is None for v in row.values())


def test_mean_corr_matches_pairwise_pearson_with_gaps():
    rng = np.random.default_rng(3)
    rows = rng.normal(size=(5, 40))
    rows[rng.random(rows.shape) < 0.2] = np.nan
    pairs = [comove_mod._corr(rows[i], rows[j]) for i in range(5) for j in range(i + 1, 5)]
    assert comove_mod._mean_corr(rows) == pytest.approx(np.mean(pairs), abs=1e-12)


def test_weeks_must_be_positive(fx):
    run_id = fx.save(_run("r1"))
    assert _comove(run_id, fx.symbols, fx.prices, "--weeks", "0").exit_code != 0
    assert "comovement" not in _show(run_id)
