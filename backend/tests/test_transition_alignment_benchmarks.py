from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from arp.transition_alignment import benchmarks
from arp.transition_alignment.benchmarks import (
    MATRIX_SECTORS,
    BenchmarksError,
    count_redlines,
    read_and_validate,
    sign_benchmarks,
)
from tests.transition_alignment_helpers import edit_bm, ta_dirs  # noqa: F401 - the fixture

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


def test_bad_types_give_lines_not_tracebacks(ta_dirs):  # noqa: F811
    out = errors_after(ta_dirs, lambda r: r["sectors"]["Steel"]["capex"].update(value="80"), resign=True)
    assert out == ["Steel: invalid capex value: expected a number"]
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
