from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from arp.config import get_settings
from arp.transition_barrier import dataset
from arp.transition_barrier.dataset import load_criteria, load_scores
from arp.transition_barrier.rule_book import (
    RuleBookNotFound,
    compute_fingerprint,
    load_rule_book,
    sign_rule_book,
)
from arp.transition_barrier.validation import count_open, validate_rule_book

FIXTURE_SRC = Path(__file__).parent / "fixtures" / "transition_barrier"


@pytest.fixture
def fixture_dir(tmp_path, monkeypatch):
    """Fixture data directory F, copied to tmp_path and wired in through the setting."""
    target = tmp_path / "transition_barrier"
    shutil.copytree(FIXTURE_SRC, target)
    monkeypatch.setenv("ARP_TRANSITION_BARRIER_DATA_DIR", str(target))
    get_settings.cache_clear()
    dataset.reset_caches()
    yield target
    get_settings.cache_clear()
    dataset.reset_caches()


def test_data_dir_setting_switches_files(fixture_dir):
    assert dataset.data_dir() == fixture_dir
    assert len(load_criteria()) == 1
    assert [s.region.value for s in load_scores()] == ["European Union", "United States", "China"]


def test_bundled_default_unchanged(monkeypatch):
    monkeypatch.delenv("ARP_TRANSITION_BARRIER_DATA_DIR", raising=False)
    get_settings.cache_clear()
    dataset.reset_caches()
    try:
        assert len(load_criteria()) == 35
        assert len(load_scores()) == 105
    finally:
        get_settings.cache_clear()
        dataset.reset_caches()


def _raw(data_dir):
    return json.loads((data_dir / "rule_book.json").read_text(encoding="utf-8"))


def test_ac91_sign(fixture_dir):
    assert sign_rule_book(fixture_dir, "owner", date(2026, 10, 18)) == 8
    raw = _raw(fixture_dir)
    assert raw["version"] == 8
    assert raw["fingerprint"] == compute_fingerprint(raw)
    assert raw["history"][-1] == {
        "version": 8,
        "fingerprint": raw["fingerprint"],
        "approved_by": "owner",
        "approved_at": "2026-10-18",
    }


def test_fixture_rule_book_is_signed_and_loads(fixture_dir):
    rule_book, raw = load_rule_book(fixture_dir)
    assert rule_book.version == 7
    assert raw["fingerprint"] == compute_fingerprint(raw)
    assert raw["history"][-1]["version"] == 7
    assert [f.id for f in rule_book.criteria["STL-R1"].facts] == ["price", "applies", "levy"]


def test_fingerprint_ignores_formatting(fixture_dir):
    raw = _raw(fixture_dir)
    raw["criteria"]["STL-R1"]["rationale"] += " Cost gap × volume."
    (fixture_dir / "rule_book.json").write_text(json.dumps(raw), encoding="utf-8")
    sign_rule_book(fixture_dir, "owner", date(2026, 10, 18))
    signed = _raw(fixture_dir)
    reordered = {k: signed[k] for k in reversed(list(signed))}
    text = json.dumps(reordered, indent=4, ensure_ascii=True)
    assert compute_fingerprint(json.loads(text)) == signed["fingerprint"]


def test_missing_rule_book(tmp_path):
    with pytest.raises(RuleBookNotFound, match=r"^Rule book not found: "):
        load_rule_book(tmp_path)


# --- validator ---------------------------------------------------------------------------


def _fx(data_dir):
    return _raw(data_dir), json.loads((data_dir / "criteria_schema.json").read_text(encoding="utf-8"))


def _check(rb, schema, resign=True):
    """Validate; re-sign first so only the mutation under test can show up."""
    if resign:
        rb["fingerprint"] = compute_fingerprint(rb)
    return validate_rule_book(rb, schema)


def _stl(rb):
    return rb["criteria"]["STL-R1"]


def _src(name):
    return {"title": name, "url": "https://example.org/" + name, "locator": "Table 1"}


def _rb2(rb, fos_unit="USD/MWh"):
    c = _stl(rb)
    c["facts"] += [
        {"id": "ren", "label": "Renewable LCOE", "type": "number", "unit": "USD/MWh", "definition": "d"},
        {"id": "fos", "label": "New-build fossil LCOE", "type": "number", "unit": fos_unit, "definition": "d"},
        {"id": "ratio", "label": "LCOE ratio", "formula": "ratio", "inputs": ["ren", "fos"], "definition": "d"},
    ]
    c["params"].append(
        {"id": "p_parity", "label": "Parity level", "value": 1, "rationale": "r", "source": _src("p_parity")}
    )
    c["levels"]["H"] = {"all": [{"fact": "ratio", "op": "<=", "param": "p_parity"}]}
    rb["version"] = 8
    return rb


def _rb6(rb):
    p = _stl(rb)["params"][0]
    del p["value"]
    p.update(status="open", question="What price closes the cost gap?")
    rb["version"] = 8
    return rb


def test_validator_accepts_f(fixture_dir):
    rb, schema = _fx(fixture_dir)
    assert validate_rule_book(rb, schema) == []
    assert count_open(rb) == 0


def test_validator_accepts_rb2_and_rb6(fixture_dir):
    rb, schema = _fx(fixture_dir)
    assert _check(_rb2(rb), schema) == []
    rb, schema = _fx(fixture_dir)
    rb = _rb6(rb)
    assert _check(rb, schema) == []
    assert count_open(rb) == 1


def test_ac77_unknown_fact(fixture_dir):
    rb, schema = _fx(fixture_dir)
    _stl(rb)["levels"]["H"]["all"][0]["fact"] = "prices"
    assert "STL-R1: condition names unknown fact 'prices'" in _check(rb, schema)


def test_unknown_parameter(fixture_dir):
    rb, schema = _fx(fixture_dir)
    _stl(rb)["levels"]["H"]["all"][0]["param"] = "p_nope"
    assert "STL-R1: condition names unknown parameter 'p_nope'" in _check(rb, schema)


def test_ac78_param_without_source(fixture_dir):
    rb, schema = _fx(fixture_dir)
    del _stl(rb)["params"][0]["source"]
    assert "STL-R1: parameter 'p_high' has no source" in _check(rb, schema)


def test_param_without_rationale(fixture_dir):
    rb, schema = _fx(fixture_dir)
    _stl(rb)["params"][0]["rationale"] = ""
    assert "STL-R1: parameter 'p_high' has no rationale" in _check(rb, schema)


def test_ac79_override_without_source(fixture_dir):
    rb, schema = _fx(fixture_dir)
    _stl(rb)["params"][0]["by_region"] = {"China": {"value": 40}}
    assert "STL-R1: parameter 'p_high' override for China has no source" in _check(rb, schema)


def test_ac80_no_rationale(fixture_dir):
    rb, schema = _fx(fixture_dir)
    _stl(rb)["rationale"] = ""
    assert "STL-R1: no rationale" in _check(rb, schema)


def test_no_facts(fixture_dir):
    rb, schema = _fx(fixture_dir)
    _stl(rb)["facts"] = []
    assert "STL-R1: no facts" in _check(rb, schema)


def test_ac81_fact_without_definition(fixture_dir):
    rb, schema = _fx(fixture_dir)
    del _stl(rb)["facts"][0]["definition"]
    assert "STL-R1: fact 'price' has no definition" in _check(rb, schema)


def test_ac82_no_m_level(fixture_dir):
    rb, schema = _fx(fixture_dir)
    del _stl(rb)["levels"]["M"]
    assert "STL-R1: no M level" in _check(rb, schema)


def test_no_h_level(fixture_dir):
    rb, schema = _fx(fixture_dir)
    del _stl(rb)["levels"]["H"]
    assert "STL-R1: no H level" in _check(rb, schema)


def test_ac83_unit_mismatch(fixture_dir):
    rb, schema = _fx(fixture_dir)
    _stl(rb)["params"][0]["unit"] = "EUR/tCO2"
    assert "STL-R1: 'price' (USD/tCO2) compared with 'p_high' (EUR/tCO2)" in _check(rb, schema)


def test_ac84_inline_number(fixture_dir):
    rb, schema = _fx(fixture_dir)
    _stl(rb)["levels"]["H"]["all"][0] = {"fact": "price", "op": ">=", "value": 50}
    assert "STL-R1: condition on 'price' uses an inline number; use a parameter" in _check(rb, schema)


def test_unknown_operator(fixture_dir):
    rb, schema = _fx(fixture_dir)
    _stl(rb)["levels"]["H"]["all"][0]["op"] = "~"
    assert "STL-R1: unknown operator '~'" in _check(rb, schema)


def test_ac85_unknown_action(fixture_dir):
    rb, schema = _fx(fixture_dir)
    _stl(rb)["actions"].append("steel.foo")
    assert "STL-R1: unknown action 'steel.foo'" in _check(rb, schema)


def test_ac86_computed_input_unit(fixture_dir):
    rb, schema = _fx(fixture_dir)
    rb = _rb2(rb, fos_unit="USD/kWh")
    assert "STL-R1: computed fact 'ratio' input 'fos' is in USD/kWh, expected USD/MWh" in _check(rb, schema)


def test_computed_unknown_and_non_numeric_input(fixture_dir):
    rb, schema = _fx(fixture_dir)
    rb = _rb2(rb)
    _stl(rb)["facts"][5]["inputs"] = ["ren", "nope"]
    assert "STL-R1: computed fact 'ratio' names unknown input 'nope'" in _check(rb, schema)
    _stl(rb)["facts"][5]["inputs"] = ["ren", "applies"]
    assert "STL-R1: computed fact 'ratio' input 'applies' is not numeric" in _check(rb, schema)


def test_ac142_nesting_depth(fixture_dir):
    rb, schema = _fx(fixture_dir)
    _stl(rb)["levels"]["M"] = {
        "all": [
            {"fact": "applies", "op": "=", "value": True},
            {"any": [{"fact": "price", "op": ">=", "param": "p_material"}, {"all": [{"fact": "levy", "op": "=", "value": True}]}]},
        ]
    }
    assert "STL-R1: conditions nested deeper than two levels" in _check(rb, schema)
    # two levels (RB4) is fine
    _stl(rb)["levels"]["M"]["all"][1]["any"][1] = {"fact": "levy", "op": "=", "value": True}
    assert _check(rb, schema) == []


def test_ac87_missing_entry(fixture_dir):
    rb, schema = _fx(fixture_dir)
    schema["criteria"].append({**schema["criteria"][0], "code": "STL-T1"})
    assert "Missing rule book entry: STL-T1" in _check(rb, schema)


def test_ac88_entry_without_criterion(fixture_dir):
    rb, schema = _fx(fixture_dir)
    rb["criteria"]["XXX-T9"] = json.loads(json.dumps(_stl(rb)))
    assert "Rule book entry without criterion: XXX-T9" in _check(rb, schema)


def test_ac89_source_without_tier(fixture_dir):
    rb, schema = _fx(fixture_dir)
    del schema["criteria"][0]["primary_sources"][2]["tier"]
    assert "Source 'steel_policy_tracker' has no tier" in _check(rb, schema)


def test_ac90_unsigned_change(fixture_dir):
    rb, schema = _fx(fixture_dir)
    _stl(rb)["params"][0]["value"] = 60
    assert validate_rule_book(rb, schema) == ["Rule book content changed but version is still 7"]


def test_open_parameter_without_question(fixture_dir):
    rb, schema = _fx(fixture_dir)
    rb = _rb6(rb)
    _stl(rb)["params"][0]["question"] = ""
    assert "STL-R1: open parameter 'p_high' has no question" in _check(rb, schema)


def test_open_parameter_skips_unit_check(fixture_dir):
    rb, schema = _fx(fixture_dir)
    rb = _rb6(rb)
    _stl(rb)["params"][0]["unit"] = "EUR/tCO2"
    assert _check(rb, schema) == []


def test_in_takes_enum_values(fixture_dir):
    rb, schema = _fx(fixture_dir)
    c = _stl(rb)
    c["facts"][1] = {"id": "scheme", "label": "Carbon pricing scheme", "type": "enum",
                     "allowed_values": ["ETS", "tax", "none"], "definition": "d"}
    c["levels"]["M"] = {"all": [{"fact": "scheme", "op": "in", "value": ["ETS", "tax"]},
                                {"fact": "price", "op": ">=", "param": "p_material"}]}
    assert _check(rb, schema) == []
    c["levels"]["M"]["all"][0]["value"] = ["ETS", "coal"]
    assert any(e.startswith("STL-R1: invalid condition on 'scheme'") for e in _check(rb, schema))


def test_boolean_and_date_values_inline(fixture_dir):
    rb, schema = _fx(fixture_dir)
    c = _stl(rb)
    c["facts"].append({"id": "start", "label": "Levy start date", "type": "date", "definition": "d"})
    c["levels"]["H"]["all"].append({"fact": "start", "op": "<=", "value": "2026-12-31"})
    assert _check(rb, schema) == []


def test_malformed_input_does_not_raise(fixture_dir):
    rb, schema = _fx(fixture_dir)
    _stl(rb)["params"][0]["value"] = "50"
    errors = _check(rb, schema)
    assert len(errors) == 1 and errors[0].startswith("STL-R1: invalid")
    for bad in (None, 5, [], "x"):
        rb, schema = _fx(fixture_dir)
        for key in ("facts", "params", "levels", "actions", "rationale"):
            _stl(rb)[key] = bad
        rb["actions"], rb["criteria"]["BAD"] = bad, bad
        assert validate_rule_book(rb, schema)
        assert validate_rule_book(bad, schema) and validate_rule_book(rb, bad)
    assert count_open({}) == 0
    rb, schema = _fx(fixture_dir)
    _stl(rb)["levels"]["H"]["all"][0].update(param=["x"], fact="price")
    assert any("invalid condition" in e for e in _check(rb, schema))


def test_malformed_schema_side_does_not_raise(fixture_dir):
    for bad in (None, 5, [], ["x"], {"x": 1}):
        rb, schema = _fx(fixture_dir)
        crit = schema["criteria"][0]
        crit["sector"] = bad
        crit["primary_sources"][0].update(key=bad, tier=bad)
        crit["primary_sources"][1] = bad
        assert isinstance(validate_rule_book(rb, schema), list)
        rb, schema = _fx(fixture_dir)
        rb["actions"]["Steel"][0]["id"] = bad
        rb["actions"]["Steel"][1] = bad
        _stl(rb)["actions"] = [bad, "steel.h2_dri"]
        assert isinstance(_check(rb, schema), list)
        rb, schema = _fx(fixture_dir)
        _stl(rb)["levels"]["H"]["all"][0].update(fact=bad)
        assert isinstance(_check(rb, schema), list)
    rb, schema = _fx(fixture_dir)
    _stl(rb)["levels"]["H"]["all"][0]["fact"] = ["price"]
    assert "STL-R1: invalid condition: fact must be an id" in _check(rb, schema)


def test_errors_come_in_rule_order(fixture_dir):
    rb, schema = _fx(fixture_dir)
    schema["criteria"][0]["primary_sources"][2].pop("tier")
    schema["criteria"].append({**schema["criteria"][0], "code": "STL-T1"})
    rb["criteria"]["XXX-T9"] = json.loads(json.dumps(_stl(rb)))
    c = _stl(rb)
    c["levels"]["H"]["all"][0]["fact"] = "prices"
    c["levels"]["H"]["all"][1] = {"fact": "levy", "op": "=", "value": True, "x": 0}
    c["levels"]["M"]["all"][1] = {"fact": "price", "op": ">=", "value": 10}
    del c["params"][0]["source"]
    c["rationale"] = ""
    del c["facts"][0]["definition"]
    c["actions"].append("steel.foo")
    errors = validate_rule_book(rb, schema)  # not re-signed: rule 9 fires too
    wanted = [
        "Missing rule book entry: STL-T1",
        "Rule book entry without criterion: XXX-T9",
        "STL-R1: condition names unknown fact 'prices'",
        "STL-R1: condition on 'price' uses an inline number; use a parameter",
        "STL-R1: parameter 'p_high' has no source",
        "STL-R1: no rationale",
        "STL-R1: fact 'price' has no definition",
        "STL-R1: unknown action 'steel.foo'",
        "Source 'steel_policy_tracker' has no tier",
        "Rule book content changed but version is still 7",
    ]
    assert all(w in errors for w in wanted)
    assert [errors.index(w) for w in wanted] == sorted(errors.index(w) for w in wanted)


# --- rules CLI ---------------------------------------------------------------------------

from typer.testing import CliRunner  # noqa: E402

from arp.cli.transition_barrier import transition_barrier_app  # noqa: E402

_runner = CliRunner()


def _rules(*args):
    return _runner.invoke(transition_barrier_app, ["rules", *args])


def _write_rb(data_dir, rb):
    (data_dir / "rule_book.json").write_text(json.dumps(rb), encoding="utf-8")


def test_ac75_cli_validate(fixture_dir):
    result = _rules("validate", "--data-dir", str(fixture_dir))
    assert result.exit_code == 0
    assert result.output == "Rule book v7: OK, 1 criteria, 0 open thresholds\n"


def test_ac76_cli_validate_open(fixture_dir):
    rb, schema = _fx(fixture_dir)
    rb = _rb6(rb)
    rb["fingerprint"] = compute_fingerprint(rb)
    _write_rb(fixture_dir, rb)
    result = _rules("validate", "--data-dir", str(fixture_dir))
    assert result.exit_code == 0
    assert result.output == "Rule book v8: OK, 1 criteria, 1 open thresholds\n"


def test_ac77_cli_validate_error(fixture_dir):
    rb, schema = _fx(fixture_dir)
    _stl(rb)["levels"]["H"]["all"][0]["fact"] = "prices"
    rb["fingerprint"] = compute_fingerprint(rb)
    _write_rb(fixture_dir, rb)
    result = _rules("validate", "--data-dir", str(fixture_dir))
    assert result.exit_code == 1
    assert "STL-R1: condition names unknown fact 'prices'" in result.output


def test_cli_validate_uses_data_dir_setting(fixture_dir):
    assert "Rule book v7: OK" in _rules("validate").output


def test_cli_validate_missing_rule_book(tmp_path):
    result = _rules("validate", "--data-dir", str(tmp_path))
    assert result.exit_code == 1
    assert result.output == f"Rule book not found: {tmp_path / 'rule_book.json'}\n"


def test_cli_validate_invalid_json(fixture_dir):
    (fixture_dir / "rule_book.json").write_text("{nope", encoding="utf-8")
    result = _rules("validate", "--data-dir", str(fixture_dir))
    assert result.exit_code == 1
    assert "rule_book.json is not valid JSON" in result.output
    assert "Traceback" not in result.output


def test_cli_validate_wrong_shape_has_no_traceback(fixture_dir):
    (fixture_dir / "rule_book.json").write_text("[]", encoding="utf-8")
    result = _rules("validate", "--data-dir", str(fixture_dir))
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_cli_sign(fixture_dir):
    rb, _ = _fx(fixture_dir)
    _stl(rb)["params"][0]["value"] = 60
    _write_rb(fixture_dir, rb)  # stale fingerprint: exactly what signing fixes
    result = _rules("sign", "--approved-by", "owner", "--data-dir", str(fixture_dir))
    assert result.exit_code == 0
    assert result.output == "Signed rule book v8\n"
    assert _rules("validate", "--data-dir", str(fixture_dir)).exit_code == 0
    assert _raw(fixture_dir)["history"][-1]["approved_at"] == date.today().isoformat()


def test_cli_sign_refuses_other_errors(fixture_dir):
    rb, _ = _fx(fixture_dir)
    _stl(rb)["levels"]["H"]["all"][0]["fact"] = "prices"
    _write_rb(fixture_dir, rb)
    before = (fixture_dir / "rule_book.json").read_text(encoding="utf-8")
    result = _rules("sign", "--approved-by", "owner", "--data-dir", str(fixture_dir))
    assert result.exit_code == 1
    assert "STL-R1: condition names unknown fact 'prices'" in result.output
    assert (fixture_dir / "rule_book.json").read_text(encoding="utf-8") == before


def test_cli_sign_missing_rule_book(tmp_path):
    result = _rules("sign", "--approved-by", "owner", "--data-dir", str(tmp_path))
    assert result.exit_code == 1
    assert result.output.startswith("Rule book not found: ")


def test_cli_render(fixture_dir, tmp_path):
    out = tmp_path / "RULE_BOOK.md"
    result = _rules("render", "--data-dir", str(fixture_dir), "--out", str(out))
    assert result.exit_code == 0
    assert out.read_text(encoding="utf-8").startswith("# Transition barrier rule book")
    assert str(out) in result.output


def test_cli_render_refuses_invalid(fixture_dir, tmp_path):
    rb, _ = _fx(fixture_dir)
    _stl(rb)["levels"]["H"]["all"][0]["fact"] = "prices"
    _write_rb(fixture_dir, rb)
    out = tmp_path / "RULE_BOOK.md"
    result = _rules("render", "--data-dir", str(fixture_dir), "--out", str(out))
    assert result.exit_code == 1
    assert "STL-R1: condition names unknown fact 'prices'" in result.output
    assert not out.exists()
