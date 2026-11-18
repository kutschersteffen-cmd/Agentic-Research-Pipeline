"""Spec theme-trend: `arp theme trend snapshot|show`, on the Acceptance section's fixture (no network)."""

import json
from datetime import date, timedelta

import numpy as np
import pytest
from typer.testing import CliRunner

from arp.cli import theme as theme_cli
from arp.config import get_settings
from arp.db.runs import RunStore
from arp.research.stock_inference.run import dump
from arp.research.stock_inference.schemas import InferRun, Mapping, Selection
from arp.schemas.taxonomy import DerivationMethod, Taxonomy
from arp.schemas.thematic import ThemeDefinition
from arp.storage.taxonomy_store import TaxonomyStore

FRIDAYS = [date(2025, 1, 3) + timedelta(weeks=i) for i in range(91)]
COLS = ["ACWI", "HOME1", "A1", "A2", "A3", "A4"]


def _prices():
    rng = np.random.default_rng(0)
    m, h1 = (rng.normal(0.0, 0.02, 90) for _ in range(2))
    t = rng.normal(0.0, 0.03, 90)
    n = [rng.normal(0.0, 0.02, 90) for _ in range(4)]
    rets = {"ACWI": m, "HOME1": h1} | {f"A{k + 1}": m + h1 + t + n[k] for k in range(4)}
    return {c: np.concatenate([[100.0], 100.0 * np.cumprod(1 + r)]) for c, r in rets.items()}


def _write_prices(path, blank=()):
    p = _prices()
    lines = ["date," + ",".join(COLS)]
    for i, d in enumerate(FRIDAYS):
        cells = ["" if any(c == b[0] and d >= date.fromisoformat(b[1]) and d <= date.fromisoformat(b[2]) for b in blank)
                 else repr(float(p[c][i])) for c in COLS]
        lines.append(d.isoformat() + "," + ",".join(cells))
    path.write_text("\n".join(lines) + "\n")
    return path


def _ret(sym, q_start, q_end):
    """R(s, q): P(last_friday) / P(prior_friday) - 1."""
    p, ds = _prices()[sym], [d.isoformat() for d in FRIDAYS]
    return p[ds.index(q_end)] / p[ds.index(q_start)] - 1


def _ex(q_start, q_end):
    return round(float(np.mean([_ret(f"A{k}", q_start, q_end) for k in range(1, 5)]) - _ret("ACWI", q_start, q_end)), 4)


def _facts(tmp_path, bad4=False):
    d = tmp_path / "facts"
    d.mkdir(exist_ok=True)
    def row(year, val, filed):
        return {"form": "10-K", "fp": "FY", "start": f"{year}-01-01", "end": f"{year}-12-31", "val": val, "filed": filed}
    rows = {1: [row(2023, 120, "2024-02-15"), row(2024, 100, "2025-02-15"), row(2025, 150, "2026-07-15")]}
    for k, v in ((2, 110), (3, 90), (4, 120)):
        rows[k] = [row(2024, 100, "2025-02-15"), row(2025, v, "2026-02-20")]
    for k, r in rows.items():
        body = {"facts": {"us-gaap": {"PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": r}}}}}
        (d / f"CIK000000000{k}.json").write_text("not json" if bad4 and k == 4 else json.dumps(body))
    return d


def _symbols(tmp_path, cik=True, no_home=None):
    rows = [f"a{k},A{k},{'' if no_home == f'a{k}' else 'HOME1'},{k}" for k in range(1, 5)]
    head = "company_id,symbol,home_index" + (",cik" if cik else "")
    p = tmp_path / "symbols.csv"
    p.write_text(head + "\n" + "".join((r if cik else r.rsplit(",", 1)[0]) + "\n" for r in rows))
    return p


@pytest.fixture
def fx(pg, tmp_path, monkeypatch):
    for var, sub in (("ARP_RUNS_DIR", "runs"), ("ARP_TAXONOMIES_DIR", "taxonomies"), ("ARP_PORTFOLIOS_DIR", "portfolios")):
        monkeypatch.setenv(var, str(tmp_path / sub))
    get_settings.cache_clear()
    tax = Taxonomy(taxonomy_id="tax_t", name="T", theme=ThemeDefinition(name="T", description="t"),
                   derivation_method=DerivationMethod.EMPIRICAL)
    TaxonomyStore(tmp_path / "taxonomies")._write_new_version(tax)
    tiers = [("a1", "core"), ("a2", "core"), ("a3", "core"), ("a4", "core"), ("a5", "adopter"), ("z1", "unknown")]
    run = InferRun(run_id="r1", stage="drafted", name="f", extractor_model="m", verifier_model="v", taxonomy_id="tax_t",
                   selection=Selection(method="sample", cutoff_reason="all"),
                   mapping=[Mapping(company_id=c, reason="r", quote="q", tier=t) for c, t in tiers])
    RunStore(pg, tmp_path / "runs").save_snapshot("r1", "infer", dump(run))

    class Fx:
        prices = _write_prices(tmp_path / "prices.csv")
        symbols = _symbols(tmp_path)
        facts = _facts(tmp_path)
        trend = tmp_path / "portfolios" / "theme_trends" / "tax_t.json"

        def run(self, *args, prices=None, symbols=None, facts=None, tax="tax_t"):
            return CliRunner().invoke(theme_cli.theme_app, [
                "trend", "snapshot", tax, "--symbols", str(symbols or self.symbols),
                "--prices", str(prices or self.prices), "--facts-dir", str(facts or self.facts), *args])

        def show(self, *args):
            return CliRunner().invoke(theme_cli.theme_app, ["trend", "show", "tax_t", *args])

        def data(self):
            return json.loads(self.trend.read_text())

    return Fx()


Q2, Q3 = ("2026-03-27", "2026-06-26"), ("2026-06-26", "2026-09-25")


def test_one_quarter(fx):
    res = fx.run("--quarter", "2026Q2")
    assert res.exit_code == 0 and res.stdout == "Saved tax_t 2026Q2\n"
    (s,) = fx.data()["snapshots"]
    assert (s["quarter"], s["quarter_end"], s["membership"], s["source"], s["taxonomy_version"]) == (
        "2026Q2", "2026-06-30", "current_mapping", "csv", 1)
    assert [m["company_id"] for m in s["members"]] == ["a1", "a2", "a3", "a4", "a5"]
    assert s["members"][4] == {"company_id": "a5", "symbol": None, "cik": None, "skipped": "no_symbol"}
    assert all(m["skipped"] is None for m in s["members"][:4])
    mk = s["market"]
    assert (mk["weeks"], mk["stocks"], mk["excess_return"], mk["direction"], mk["skipped"]) == (13, 4, _ex(*Q2), "up", None)
    assert mk["acwi_return"] == round(_ret("ACWI", *Q2), 4)
    cv = s["comovement"]
    assert (cv["window_weeks"], cv["stocks"], cv["p_value"], cv["skipped"]) == (52, 4, 0.002, None)
    assert cv["mean_resid_corr"] > cv["null_p95"]
    assert s["diffusion"]["capex"] == {"companies": 4, "rising": 2, "share": 0.5, "direction": "flat", "skipped": None}
    assert s["diffusion"]["rnd"] == {"companies": 0, "rising": 0, "share": None, "direction": None,
                                     "skipped": "too_few_companies"}


def test_range_and_point_in_time_filings(fx):
    res = fx.run("--from", "2026Q2", "--to", "2026Q3")
    assert res.stdout == "Saved tax_t 2026Q2\nSaved tax_t 2026Q3\n"
    q2, q3 = fx.data()["snapshots"]
    assert (q3["market"]["excess_return"], q3["market"]["direction"]) == (_ex(*Q3), "down")
    assert q3["diffusion"]["capex"] == {"companies": 4, "rising": 3, "share": 0.75, "direction": "up", "skipped": None}
    assert q2["diffusion"]["capex"]["rising"] == 2  # a1's FY2025 filing came after 2026-06-30


def test_rerun_replaces_only_its_quarter_and_keeps_order(fx, tmp_path):
    assert fx.run("--quarter", "2026Q3").exit_code == 0
    gapped = _write_prices(tmp_path / "gap.csv", blank=[("A4", "2026-05-15", "2026-05-15")])
    assert fx.run("--quarter", "2026Q2", prices=gapped).exit_code == 0
    assert [s["market"]["stocks"] for s in fx.data()["snapshots"]] == [3, 4]
    q3 = fx.data()["snapshots"][1]
    assert fx.run("--quarter", "2026Q2").exit_code == 0
    snaps = fx.data()["snapshots"]
    assert [s["quarter"] for s in snaps] == ["2026Q2", "2026Q3"] and snaps[0]["market"]["stocks"] == 4 and snaps[1] == q3


def test_missing_prices_skip(fx, tmp_path):
    one = _write_prices(tmp_path / "one.csv", blank=[("A4", "2026-08-14", "2026-08-14")])
    assert fx.run("--quarter", "2026Q3", prices=one).exit_code == 0
    assert fx.data()["snapshots"][0]["market"]["stocks"] == 3
    two = _write_prices(tmp_path / "two.csv", blank=[("A3", "2026-07-03", "2026-12-31"), ("A4", "2026-07-03", "2026-12-31")])
    assert fx.run("--quarter", "2026Q3", prices=two).exit_code == 0
    mk = fx.data()["snapshots"][0]["market"]
    assert (mk["skipped"], mk["excess_return"], mk["direction"]) == ("too_few_stocks", None, None)


def test_quarter_before_prices_start_has_short_control(fx):
    assert fx.run("--quarter", "2025Q1").exit_code == 0
    s = fx.data()["snapshots"][0]
    assert s["market"]["skipped"] == "short_control" and s["comovement"]["skipped"] == "short_control"


def test_no_cik_column_means_no_diffusion(fx, tmp_path):
    assert fx.run("--quarter", "2026Q2", symbols=_symbols(tmp_path, cik=False)).exit_code == 0
    capex = fx.data()["snapshots"][0]["diffusion"]["capex"]
    assert (capex["companies"], capex["skipped"]) == (0, "too_few_companies")


@pytest.mark.parametrize(("args", "message"), [
    (("--quarter", "2099Q1"), "Quarter 2099Q1 has not ended."),
    (("--quarter", "2026-3"), "Quarter 2026-3 is not in the form YYYYQn."),
    ((), "Give --quarter, or --from and --to."),
    (("--quarter", "2026Q2", "--from", "2026Q1", "--to", "2026Q2"), "Give --quarter, or --from and --to."),
    (("--from", "2026Q2"), "Give --quarter, or --from and --to."),
    (("--from", "2026Q3", "--to", "2026Q2"), "--from 2026Q3 is after --to 2026Q2."),
])
def test_refusals_write_nothing(fx, args, message):
    res = fx.run(*args)
    assert res.exit_code == 1 and res.stderr.strip() == message and not fx.trend.exists()


def test_unknown_taxonomy_and_no_mapping(fx, tmp_path):
    res = fx.run("--quarter", "2026Q2", tax="tax_nope")
    assert res.exit_code == 1 and res.stderr.strip() == "Taxonomy tax_nope not found."
    hand = Taxonomy(taxonomy_id="tax_hand", name="H", theme=ThemeDefinition(name="H", description="h"),
                    derivation_method=DerivationMethod.EMPIRICAL)
    TaxonomyStore(tmp_path / "taxonomies")._write_new_version(hand)
    res = fx.run("--quarter", "2026Q2", tax="tax_hand")
    assert res.exit_code == 1 and res.stderr.strip() == (
        "Taxonomy tax_hand has no stock mapping; trend needs a taxonomy made by 'arp taxonomy infer pick'.")


def test_failed_calls_leave_the_file_byte_identical(fx, tmp_path):
    assert fx.run("--quarter", "2026Q2").exit_code == 0
    before = fx.trend.read_bytes()
    res = fx.run("--from", "2026Q3", "--to", "2099Q1")
    assert res.exit_code == 1 and res.stderr.strip() == "Quarter 2099Q1 has not ended."
    res = fx.run("--quarter", "2026Q3", symbols=_symbols(tmp_path, no_home="a3"))
    assert res.exit_code == 1 and res.stderr.strip() == "Stock a3 has no home_index."
    res = fx.run("--from", "2026Q2", "--to", "2026Q3", facts=_facts(tmp_path, bad4=True))
    assert res.exit_code != 0
    assert fx.trend.read_bytes() == before


def test_show_table(fx):
    assert fx.run("--from", "2026Q2", "--to", "2026Q3").exit_code == 0
    lines = fx.show().stdout.splitlines()
    assert lines[0] == ("quarter\texcess_return\tmarket\tmean_resid_corr\tcorr_change\tcapex_share\tcapex_change\tcapex\t"
                        "rnd_share\trnd_change\trnd")
    assert len(lines) == 3 and lines[2].startswith("2026Q3\t")
    first, second = (ln.split("\t") for ln in lines[1:])
    assert second[6] == "0.2500"
    assert [first[4], first[6], first[9], first[8], first[10]] == ["n/a"] * 5
    assert json.loads(fx.show("--json").stdout) == fx.data()


def test_show_change_needs_the_calendar_quarter_just_before(fx):
    assert fx.run("--quarter", "2025Q4").exit_code == 0
    assert fx.run("--quarter", "2026Q2").exit_code == 0
    assert all(s["comovement"]["mean_resid_corr"] is not None for s in fx.data()["snapshots"])
    assert fx.show().stdout.splitlines()[-1].split("\t")[4] == "n/a"


def test_show_without_a_file(fx):
    res = fx.show()
    assert res.exit_code == 1 and res.stderr.strip() == "No trend stored for tax_t."


def test_same_inputs_same_file_and_no_model_key(fx, monkeypatch):
    monkeypatch.delenv("ARP_ANTHROPIC_API_KEY", raising=False)
    assert fx.run("--from", "2026Q2", "--to", "2026Q3").exit_code == 0
    first = fx.trend.read_bytes()
    fx.trend.unlink()
    monkeypatch.setenv("ARP_ANTHROPIC_API_KEY", "dummy")
    assert fx.run("--from", "2026Q2", "--to", "2026Q3").exit_code == 0
    assert fx.trend.read_bytes() == first


def test_skipped_blocks_keep_their_counts(fx):
    assert fx.run("--quarter", "2025Q1").exit_code == 0
    s = fx.data()["snapshots"][0]
    assert (s["market"]["weeks"], s["market"]["stocks"]) == (13, 0)
    assert (s["comovement"]["window_weeks"], s["comovement"]["stocks"]) == (52, 0)


def test_cik_is_kept_as_typed(fx, tmp_path):
    p = tmp_path / "typed.csv"
    p.write_text("company_id,symbol,home_index,cik\na1,A1,HOME1, 0000000001\na2,A2,HOME1,n/a\na3,A3,HOME1,3\na4,A4,HOME1,4\n")
    assert fx.run("--quarter", "2026Q2", symbols=p).exit_code == 0
    assert [m["cik"] for m in fx.data()["snapshots"][0]["members"]] == ["0000000001", "n/a", "3", "4", None]


def test_unreadable_trend_file_is_refused_and_untouched(fx):
    fx.trend.parent.mkdir(parents=True)
    for bad in ("not json", json.dumps({"taxonomy_id": "other", "snapshots": []})):
        fx.trend.write_text(bad)
        res = fx.run("--quarter", "2026Q2")
        assert res.exit_code == 1 and res.stderr.startswith("Trend file for tax_t is unreadable: ")
        assert fx.trend.read_text() == bad
        assert fx.show().exit_code == 1


def test_unknown_taxonomy_creates_no_directory(fx, tmp_path):
    assert fx.run("--quarter", "2026Q2", tax="tax_nope").exit_code == 1
    assert not (tmp_path / "taxonomies" / "tax_nope").exists()


def test_date_overflow_exits_nonzero_and_writes_nothing(fx):
    res = fx.run("--from", "0001Q1", "--to", "2026Q2")
    assert res.exit_code != 0 and not fx.trend.exists()


def test_first_run_in_sorted_order_supplies_the_members(fx, pg, tmp_path):
    store = RunStore(pg, tmp_path / "runs")
    data = store.read_snapshot("r1", "infer")
    store.save_snapshot("r0", "infer", {**data, "run_id": "r0", "mapping": data["mapping"][:3]})
    assert fx.run("--quarter", "2026Q2").exit_code == 0
    s = fx.data()["snapshots"][0]
    assert s["run_id"] == "r0" and [m["company_id"] for m in s["members"]] == ["a1", "a2", "a3"]
