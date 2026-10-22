from __future__ import annotations

import asyncio
import json
import re
import shutil
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.cli.transition_alignment import transition_alignment_app
from arp.transition_alignment import benchmarks
from arp.transition_alignment.benchmarks import (
    MATRIX_SECTORS,
    BenchmarksError,
    count_redlines,
    read_and_validate,
    sign_benchmarks,
)
from tests.transition_alignment_helpers import FIXTURES, _reset, edit_bm, ta_dirs  # noqa: F401 - the fixture

BUNDLED_SCHEMA = Path(benchmarks.__file__).parents[1] / "transition_barrier" / "data" / "criteria_schema.json"


def errors(dirs) -> list[str]:
    f_ta, bm = dirs
    return read_and_validate(bm, f_ta)[1]


def errors_after(dirs, fn, resign=False) -> list[str]:
    edit_bm(dirs[1], fn)
    if resign:
        sign_benchmarks(dirs[1], "test", date(2026, 10, 19))
    return errors(dirs)


def test_bm_fixture_is_valid(ta_dirs):  # noqa: F811
    assert errors(ta_dirs) == []
    raw, _ = read_and_validate(ta_dirs[1], ta_dirs[0])
    assert raw["version"] == 3
    assert count_redlines(raw) == 2


def test_ac3_capex_no_source(ta_dirs):  # noqa: F811
    out = errors_after(ta_dirs, lambda r: r["sectors"]["Steel"]["capex"].pop("source"), resign=True)
    assert out == ["Steel: capex benchmark has no source"]


def test_rnd_and_redline_no_source(ta_dirs):  # noqa: F811
    def fn(r):
        r["sectors"]["Steel"]["rnd_tests"][0]["source"] = {"title": " "}
        r["sectors"]["Steel"]["redlines"][0].pop("source")

    assert errors_after(ta_dirs, fn, resign=True) == [
        "Steel: R&D test 'lc_share' has no source",
        "Steel: redline 'stl_bf' has no source",
    ]


def test_ac4_unknown_sector(ta_dirs):  # noqa: F811
    def fn(r):
        r["sectors"]["Aluminium"] = {**json.loads(json.dumps(r["sectors"]["Cement"])), "isic_prefixes": ["242"]}

    assert "Sector not in the transition-barrier matrix: Aluminium" in errors_after(ta_dirs, fn)


def test_missing_sector_entry(ta_dirs):  # noqa: F811
    assert "Missing benchmarks entry: Steel" in errors_after(ta_dirs, lambda r: r["sectors"].pop("Steel"))


def test_ac5_prefix_overlap(ta_dirs):  # noqa: F811
    out = errors_after(ta_dirs, lambda r: r["sectors"]["Cement"].update(isic_prefixes=["24"]))
    assert out.count("ISIC prefix '24' is in two sectors") == 1


def test_ac6_stale_fingerprint(ta_dirs):  # noqa: F811
    out = errors_after(ta_dirs, lambda r: r["sectors"]["Steel"]["capex"].update(value=75))
    assert out == ["Benchmarks content changed but version is still 3"]


def test_ac7_missing_lever(ta_dirs):  # noqa: F811
    assert "No ACT lever entry for action: steel.ccus" in errors_after(ta_dirs, lambda r: r["act_levers"].pop("steel.ccus"))


def test_ac64_unknown_lever(ta_dirs):  # noqa: F811
    out = errors_after(ta_dirs, lambda r: r["act_levers"].update({"pwr.renewables": None}))
    assert "Unknown action in act_levers: pwr.renewables" in out


def test_ac8_unit_mismatch(ta_dirs):  # noqa: F811
    out = errors_after(ta_dirs, lambda r: r["assumptions"]["h2_cost"]["barrier_facts"].append("STL-R1.price"))
    assert "Assumption 'h2_cost' is in USD/kg H2, 'STL-R1.price' is in USD/tCO2" in out


def test_unknown_barrier_fact(ta_dirs):  # noqa: F811
    out = errors_after(ta_dirs, lambda r: r["assumptions"]["carbon_price"]["barrier_facts"].append("STL-R1.nope"))
    assert "Assumption 'carbon_price' names unknown barrier fact 'STL-R1.nope'" in out


def test_unknown_field(ta_dirs):  # noqa: F811
    out = errors_after(ta_dirs, lambda r: r["sectors"]["Steel"]["redlines"][0].update(fact="tc_nope"))
    assert "Steel: unknown field 'tc_nope'" in out


def test_errors_in_rule_order(ta_dirs):  # noqa: F811
    def fn(r):
        r["sectors"]["Steel"]["capex"]["value"] = 75
        r["act_levers"].pop("steel.ccus")
        r["sectors"]["Steel"]["redlines"][0]["fact"] = "tc_nope"
        r["sectors"]["Steel"]["capex"].pop("source")
        r["sectors"]["Aluminium"] = r["sectors"]["Cement"] | {"isic_prefixes": ["242"]}

    assert errors_after(ta_dirs, fn) == [
        "Sector not in the transition-barrier matrix: Aluminium",
        "Steel: capex benchmark has no source",
        "Steel: unknown field 'tc_nope'",
        "No ACT lever entry for action: steel.ccus",
        "Benchmarks content changed but version is still 3",
    ]


def test_ac67_sign(ta_dirs):  # noqa: F811
    edit_bm(ta_dirs[1], lambda r: r["sectors"]["Steel"]["capex"].update(value=75))
    assert sign_benchmarks(ta_dirs[1], "owner", date(2026, 10, 19)) == 4
    raw = json.loads((ta_dirs[1] / "benchmarks.json").read_text(encoding="utf-8"))
    assert raw["version"] == 4
    assert raw["history"][-1]["version"] == 4
    assert raw["history"][-1]["approved_by"] == "owner"
    assert raw["history"][-1]["approved_at"] == "2026-10-19"
    assert errors(ta_dirs) == []
    assert count_redlines(raw) == 2


def test_benchmark_values_must_be_above_zero(ta_dirs):  # noqa: F811
    for bad in (0, -5, float("nan"), float("inf")):
        out = errors_after(ta_dirs, lambda r, v=bad: r["sectors"]["Steel"]["capex"].update(value=v), resign=True)
        assert out == ["Steel: invalid capex value: expected a number above 0"], bad
    def rnd_zero(r):
        r["sectors"]["Steel"]["capex"].update(value=80)  # edits accumulate in the same dir
        r["sectors"]["Steel"]["rnd_tests"][0].update(value=0)

    out = errors_after(ta_dirs, rnd_zero, resign=True)
    assert out == ["Steel: invalid R&D test 'lc_share' value: expected a number above 0"]


def test_bad_types_give_lines_not_tracebacks(ta_dirs):  # noqa: F811
    out = errors_after(ta_dirs, lambda r: r["sectors"]["Steel"]["capex"].update(value="80"), resign=True)
    assert out == ["Steel: invalid capex value: expected a number above 0"]
    good = (ta_dirs[1] / "benchmarks.json").read_text(encoding="utf-8")
    for fn in (
        lambda r: r.update(sectors=[]),
        lambda r: r.update(act_levers="x", assumptions=[1]),
        lambda r: r["sectors"].update(Steel=None),
        lambda r: r["sectors"]["Steel"].update(rnd_tests="x", redlines=[None], isic_prefixes=[1]),
        lambda r: r["assumptions"].update(h2_cost={"barrier_facts": ["no-dot", 3]}),
    ):
        (ta_dirs[1] / "benchmarks.json").write_text(good, encoding="utf-8")
        out = errors_after(ta_dirs, fn)
        assert out and all(isinstance(e, str) for e in out)


def test_model_backstop(ta_dirs):  # noqa: F811
    out = errors_after(ta_dirs, lambda r: r.update(version="3"), resign=False)
    assert "Benchmarks: invalid version: Input should be a valid integer" in out


def test_load_and_lookup(ta_dirs):  # noqa: F811
    b = benchmarks.load_benchmarks()
    assert benchmarks.sector_for_isic(b, "2410") == "Steel"
    assert benchmarks.sector_for_isic(b, "1050") is None
    assert benchmarks.sector_for_isic(b, None) is None
    assert benchmarks.citation(b.sectors["Steel"].capex.source) == "ACT Core methodology p.62"
    assert benchmarks.citation(b.sectors["Steel"].redlines[0].source) == "owner-defined (2026-10-19)"


def test_check_benchmarks_names_first_error(ta_dirs):  # noqa: F811
    edit_bm(ta_dirs[1], lambda r: r["sectors"]["Steel"]["capex"].pop("source"))
    with pytest.raises(BenchmarksError, match="^Steel: capex benchmark has no source$"):
        benchmarks.check_benchmarks()


def test_matrix_sectors_match_bundled_schema():
    criteria = json.loads(BUNDLED_SCHEMA.read_text(encoding="utf-8"))["criteria"]
    assert list(MATRIX_SECTORS) == list(dict.fromkeys(c["sector"] for c in criteria))


def test_missing_file(tmp_path):
    with pytest.raises(BenchmarksError) as exc:
        read_and_validate(tmp_path, tmp_path)
    assert str(exc.value).startswith("Benchmarks not found: ")


def test_invalid_json(tmp_path):
    (tmp_path / "benchmarks.json").write_text("{", encoding="utf-8")
    with pytest.raises(BenchmarksError, match="^benchmarks.json is not valid JSON: "):
        read_and_validate(tmp_path, tmp_path)


# --- CLI, app startup and GET /api/transition-alignment/benchmarks (task 3) ---

_runner = CliRunner()


def _cli(*args: str):
    return _runner.invoke(transition_alignment_app, ["benchmarks", *args])


@pytest.fixture
def bundled_dirs(monkeypatch):
    """Both data-dir settings unset, so the bundled barrier and benchmarks directories are used."""
    monkeypatch.delenv("ARP_TRANSITION_BARRIER_DATA_DIR", raising=False)
    monkeypatch.delenv("ARP_TRANSITION_ALIGNMENT_DATA_DIR", raising=False)
    _reset()
    yield
    _reset()


def test_ac66_bundled_validates(bundled_dirs):
    raw = json.loads((benchmarks.data_dir() / benchmarks.BENCHMARKS_FILE).read_text(encoding="utf-8"))
    result = _cli("validate")
    assert result.exit_code == 0, result.output
    assert result.output == f"Benchmarks v{raw['version']}: OK, 9 sectors, 3 redlines\n"


@pytest.mark.parametrize(
    ("fn", "expected"),
    [
        (lambda r: r["sectors"]["Steel"]["capex"].pop("source"), "Steel: capex benchmark has no source"),  # AC-3
        (
            lambda r: r["sectors"].update(Aluminium={**r["sectors"]["Cement"], "isic_prefixes": ["242"]}),
            "Sector not in the transition-barrier matrix: Aluminium",
        ),  # AC-4
        (lambda r: r["sectors"]["Cement"].update(isic_prefixes=["24"]), "ISIC prefix '24' is in two sectors"),  # AC-5
        (
            lambda r: r["sectors"]["Steel"]["capex"].update(value=75),
            "Benchmarks content changed but version is still 3",
        ),  # AC-6
        (lambda r: r["act_levers"].pop("steel.ccus"), "No ACT lever entry for action: steel.ccus"),  # AC-7
        (
            lambda r: r["assumptions"]["h2_cost"].update(barrier_facts=["STL-R1.price"]),
            "Assumption 'h2_cost' is in USD/kg H2, 'STL-R1.price' is in USD/tCO2",
        ),  # AC-8
        (lambda r: r["act_levers"].update({"pwr.renewables": None}), "Unknown action in act_levers: pwr.renewables"),  # AC-64
    ],
)
def test_ac3_cli(ta_dirs, fn, expected):  # noqa: F811
    edit_bm(ta_dirs[1], fn)
    result = _cli("validate", "--data-dir", str(ta_dirs[1]))
    assert result.exit_code == 1
    assert expected in result.output.splitlines()


def test_ac67_cli(ta_dirs):  # noqa: F811
    bm = ta_dirs[1]
    edit_bm(bm, lambda r: r["sectors"]["Steel"]["capex"].update(value=75))
    signed = _cli("sign", "--approved-by", "owner", "--data-dir", str(bm))
    assert signed.exit_code == 0, signed.output
    assert signed.output == "Signed benchmarks v4\n"
    raw = json.loads((bm / benchmarks.BENCHMARKS_FILE).read_text(encoding="utf-8"))
    assert raw["version"] == 4
    assert (raw["history"][-1]["version"], raw["history"][-1]["approved_by"]) == (4, "owner")
    result = _cli("validate", "--data-dir", str(bm))
    assert result.exit_code == 0, result.output
    assert result.output == "Benchmarks v4: OK, 3 sectors, 2 redlines\n"


def test_sign_refuses_other_errors(ta_dirs):  # noqa: F811
    bm = ta_dirs[1]
    edit_bm(bm, lambda r: r["sectors"]["Steel"]["capex"].pop("source"))
    result = _cli("sign", "--approved-by", "owner", "--data-dir", str(bm))
    assert result.exit_code == 1
    assert "Steel: capex benchmark has no source" in result.output.splitlines()
    assert json.loads((bm / benchmarks.BENCHMARKS_FILE).read_text(encoding="utf-8"))["version"] == 3


def test_ac57_startup_refused(ta_dirs, monkeypatch):  # noqa: F811
    from arp.api import main

    monkeypatch.setattr(main, "require_postgres", lambda settings: None)
    edit_bm(ta_dirs[1], lambda r: r["sectors"]["Steel"]["capex"].pop("source"))

    async def start():
        async with main.lifespan(main.app):
            pass

    with pytest.raises(BenchmarksError, match=re.escape("Steel: capex benchmark has no source")):
        asyncio.run(start())


def test_ac2_benchmarks_api(bundled_dirs):
    from arp.api.main import app

    response = TestClient(app).get("/api/transition-alignment/benchmarks")
    assert response.status_code == 200, response.text
    body = response.json()
    capex = {s["sector"]: s["capex"] for s in body["sectors"]}
    assert len(capex) == 9
    special = {"Power & Utilities": 95, "Oil & Gas Upstream": 77, "Chemicals": 77}
    assert {name: c["value"] for name, c in capex.items()} == {name: special.get(name, 80) for name in capex}
    assert all("p." in c["citation"] for c in capex.values())


# --- Scenario prices (benchmarks v2) ---


def _use_bm_s(dirs) -> None:
    shutil.copy(FIXTURES / "bm_s" / benchmarks.BENCHMARKS_FILE, dirs[1] / benchmarks.BENCHMARKS_FILE)


def test_bm_s_fixture_is_valid(ta_dirs):  # noqa: F811
    _use_bm_s(ta_dirs)
    assert errors(ta_dirs) == []
    assert [g.group for g in benchmarks.load_benchmarks().scenario_prices] == ["advanced economies", "selected EMDE"]


def test_bm_without_key_still_valid(ta_dirs):  # noqa: F811
    assert "scenario_prices" not in json.loads((ta_dirs[1] / benchmarks.BENCHMARKS_FILE).read_text(encoding="utf-8"))
    assert errors(ta_dirs) == []
    assert benchmarks.load_benchmarks().scenario_prices == []


def test_ac87_scenario_no_source(ta_dirs):  # noqa: F811
    _use_bm_s(ta_dirs)
    edit_bm(ta_dirs[1], lambda r: r["scenario_prices"][0].pop("source"))
    result = _cli("validate", "--data-dir", str(ta_dirs[1]))
    assert result.exit_code == 1
    assert "Scenario prices: advanced economies has no source" in result.output.splitlines()


def test_scenario_unknown_group(ta_dirs):  # noqa: F811
    _use_bm_s(ta_dirs)
    got = errors_after(ta_dirs, lambda r: r["scenario_prices"][1].update(group="Mars"))
    assert "Scenario prices: unknown region group 'Mars'" in got


def test_scenario_missing_in_bundled_refused(tmp_path, bundled_dirs, monkeypatch):
    bundled = tmp_path / "bundled"
    shutil.copytree(benchmarks.BUNDLED_DIR, bundled)
    monkeypatch.setattr(benchmarks, "BUNDLED_DIR", bundled)
    edit_bm(bundled, lambda r: r.pop("scenario_prices"))
    result = _cli("validate", "--data-dir", str(bundled))
    assert result.exit_code == 1
    assert "Scenario prices: missing" in result.output.splitlines()


def test_ac113_api(bundled_dirs):
    from arp.api.main import app

    body = TestClient(app).get("/api/transition-alignment/benchmarks").json()
    groups = {g["group"]: g for g in body["scenario_prices"]}
    assert groups["advanced economies"]["prices"] == {"2030": 140, "2035": 180, "2040": 205, "2050": 250}
    assert groups["selected EMDE"]["prices"] == {"2030": 90, "2035": 125, "2040": 160, "2050": 200}
    assert all("p.329" in g["citation"] for g in groups.values())


# --- Delivery KPIs (benchmarks v3) ---


def _sectors_api() -> dict[str, dict]:
    from arp.api.main import app

    body = TestClient(app).get("/api/transition-alignment/benchmarks").json()
    return {s["sector"]: s for s in body["sectors"]} | {"_version": body["version"]}


def test_ac178_to_182_delivery_kpis_api(bundled_dirs):
    s = _sectors_api()
    assert s["_version"] == 3
    kpis = {name: e["delivery_kpis"] for name, e in s.items() if name != "_version"}
    assert [(k["id"], k["range_text"], k["cite"]) for k in kpis["Aviation"]] == [
        ("saf_share", "0% → 11% (2030) → 26% (2035) → 70% (2050)", "IEA Net Zero Roadmap 2023, p.94")
    ]  # AC-178
    assert [(k["id"], k["range_text"], k["cite"]) for k in kpis["Shipping"]] == [
        ("ship_lc_fuel_share", "0% → 19% (2030) → 36% (2035) → 85% (2050)", "IEA Net Zero Roadmap 2023, p.94")
    ]  # AC-179
    assert [(k["id"], k["range_text"], k["levers"], k["cite"]) for k in kpis["Oil & Gas Upstream"]] == [
        ("ccs_capex_share", "0% → 5%", [], "ACT Oil & Gas, OG 2.6, pp.57–58; benchmark p.126")
    ]  # AC-180
    assert [(k["id"], k["isic_prefixes"]) for k in kpis["Heavy-Duty Road Transport"]] == [
        ("zev_sales_share", ["2910"]),
        ("fleet_lc_share", ["4923"]),
    ]  # AC-181
    assert [kpis[n] for n in ("Steel", "Power & Utilities", "Critical Minerals & Mining")] == [[], [], []]  # AC-182
    assert sum(len(v) for v in kpis.values()) == 9
    cement = kpis["Cement"][0]
    assert cement == {
        "id": "alt_fuel_share",
        "label": "Alternative-fuel share of kiln heat",
        "field_id": "tc_alt_fuel_share_pct",
        "isic_prefixes": ["2394"],
        "range_text": "0% → 30%",
        "levers": ["cement.alt_fuels"],
        "cite": "ACT Cement v2.0, CEM 2.4a, p.50",
    }


def test_ac183_bundled_v3_validates(bundled_dirs):
    result = _cli("validate")
    assert result.exit_code == 0, result.output
    assert result.output == "Benchmarks v3: OK, 9 sectors, 3 redlines\n"


def test_ac199_v2_blocks_unchanged(bundled_dirs):
    v2 = json.loads((FIXTURES / "bm_v2_sectors.json").read_text(encoding="utf-8"))
    v3 = json.loads((benchmarks.BUNDLED_DIR / benchmarks.BENCHMARKS_FILE).read_text(encoding="utf-8"))["sectors"]
    keys = ("isic_prefixes", "capex", "rnd_tests", "redlines")
    assert {s: {k: e.get(k) for k in keys} for s, e in v3.items()} == {s: {k: e.get(k) for k in keys} for s, e in v2.items()}


def _cement_kpi(fn):
    return lambda r: fn(r["sectors"]["Cement"]["delivery_kpis"][0])


@pytest.mark.parametrize(
    ("fn", "needles"),
    [
        (_cement_kpi(lambda k: k.update(points=[{"value": 30}, {"value": 20}])), ("Cement", "alt_fuel_share")),  # AC-184
        (_cement_kpi(lambda k: k.update(field="tc_unknown_pct")), ("tc_unknown_pct",)),  # AC-185
        (_cement_kpi(lambda k: k.update(isic_prefixes=["9999"])), ("alt_fuel_share",)),  # AC-192
        (_cement_kpi(lambda k: k.update(points=[{"value": 120}])), ("alt_fuel_share",)),  # AC-193
        (_cement_kpi(lambda k: k.update(cite="ACT Cement v2.0")), ("alt_fuel_share",)),  # AC-195
        (
            lambda r: (
                r["sectors"]["Cement"].update(isic_prefixes=["2394", "2395"]),
                r["sectors"]["Cement"]["delivery_kpis"][0].update(isic_prefixes=["2395"]),
            ),
            ("alt_fuel_share",),
        ),  # AC-204
        (_cement_kpi(lambda k: k.update(cite="ACT Cement Corp. v2.0")), ("alt_fuel_share",)),  # AC-205
    ],
)
def test_delivery_kpi_cli(ta_dirs, fn, needles):  # noqa: F811
    edit_bm(ta_dirs[1], fn)
    result = _cli("validate", "--data-dir", str(ta_dirs[1]))
    assert result.exit_code != 0
    assert any(all(n in line for n in needles) for line in result.output.splitlines()), result.output


def test_ac194_years_must_rise(tmp_path, bundled_dirs):
    copy = tmp_path / "bundled"
    shutil.copytree(benchmarks.BUNDLED_DIR, copy)
    backwards = [{"value": 11, "year": 2035}, {"value": 26, "year": 2030}]
    edit_bm(copy, lambda r: r["sectors"]["Aviation"]["delivery_kpis"][0].update(points=backwards))
    result = _cli("validate", "--data-dir", str(copy))
    assert result.exit_code != 0
    assert any("saf_share" in line for line in result.output.splitlines()), result.output


def test_delivery_kpi_lines(ta_dirs):  # noqa: F811
    head = "Cement: delivery KPI 'alt_fuel_share'"
    assert errors_after(ta_dirs, _cement_kpi(lambda k: k.update(field="tc_unknown_pct")), resign=True) == [
        f"{head}: unknown field 'tc_unknown_pct'"
    ]
    assert errors_after(ta_dirs, _cement_kpi(lambda k: k.update(field="tc_saf_share_pct")), resign=True) == [
        f"{head}: field 'tc_saf_share_pct' does not apply to ISIC prefix '2394'"
    ]


def test_delivery_kpi_bad_shapes_give_one_line(ta_dirs):  # noqa: F811  Review Focus 4
    good = (ta_dirs[1] / "benchmarks.json").read_text(encoding="utf-8")
    for fn, n in (
        (lambda r: r["sectors"]["Cement"].update(delivery_kpis="x"), 1),
        (_cement_kpi(lambda k: k.update(points=[{"value": "a"}])), 1),
        (lambda r: r["sectors"]["Cement"].update(delivery_kpis=[None]), 1),
        (_cement_kpi(lambda k: k.update(points="x")), 1),
        (_cement_kpi(lambda k: k.update(field=["x"], isic_prefixes="x", cite=None)), 3),
        (lambda r: r["sectors"]["Cement"].update(isic_prefixes=[["2394"]]), 1),
    ):
        (ta_dirs[1] / "benchmarks.json").write_text(good, encoding="utf-8")
        edit_bm(ta_dirs[1], fn)
        sign_benchmarks(ta_dirs[1], "test", date(2026, 10, 19))
        result = _cli("validate", "--data-dir", str(ta_dirs[1]))
        assert result.exit_code != 0
        assert len(result.output.strip().splitlines()) == n, result.output


def test_range_text():
    from arp.transition_alignment.benchmarks import KpiPoint, range_text

    assert range_text([KpiPoint(value=30)]) == "0% → 30%"
    assert range_text([KpiPoint(value=95, year=2040)]) == "0% → 95% (2040)"
    pts = [KpiPoint(value=37, year=2030), KpiPoint(value=65, year=2035), KpiPoint(value=100, year=2050)]
    assert range_text(pts) == "0% → 37% (2030) → 65% (2035) → 100% (2050)"


def test_kpi_prefixes_fall_back_to_sector(bundled_dirs):
    b = benchmarks.load_benchmarks()
    hdt, cement = b.sectors["Heavy-Duty Road Transport"], b.sectors["Cement"]
    assert benchmarks.kpi_prefixes(hdt, hdt.delivery_kpis[1]) == ["4923"]
    assert benchmarks.kpi_prefixes(cement, cement.delivery_kpis[0]) == ["2394"]
    assert cement.delivery_kpis[0].isic_prefixes == []
