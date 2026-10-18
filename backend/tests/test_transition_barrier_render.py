from __future__ import annotations

import copy
import json

import pytest

from arp.transition_barrier.render import fmt_number, render_group, render_rule_book_md, rubric
from arp.transition_barrier.rule_book import CriterionRules, load_rule_book
from tests.test_transition_barrier_rule_book import _rb2, _rb6, _src, _stl, fixture_dir  # noqa: F401


@pytest.fixture
def raw_f(fixture_dir):  # noqa: F811
    _, raw = load_rule_book(fixture_dir)
    return raw


def _rules(raw):
    return CriterionRules.model_validate(_stl(copy.deepcopy(raw)))


def _variant(raw, mutate):
    raw = copy.deepcopy(raw)
    mutate(_stl(raw))
    return _rules(raw)


def test_ac93_fixture_rubric(raw_f):
    assert rubric(_rules(raw_f)) == {
        "H": "Effective carbon price >= 50 USD/tCO2 and Border levy in force is Yes",
        "M": "Carbon price applies to steel is Yes and Effective carbon price >= 10 USD/tCO2",
        "L": "Otherwise (neither H nor M holds)",
    }


def test_ac14_nested_group_in_brackets(raw_f):
    def m(c):
        c["levels"]["M"] = {
            "all": [
                {"fact": "applies", "op": "=", "value": True},
                {"any": [{"fact": "price", "op": ">=", "param": "p_material"}, {"fact": "levy", "op": "=", "value": True}]},
            ]
        }

    assert rubric(_variant(raw_f, m))["M"] == (
        "Carbon price applies to steel is Yes and (Effective carbon price >= 10 USD/tCO2 or Border levy in force is Yes)"
    )


def test_any_joins_with_or(raw_f):
    def m(c):
        c["levels"]["M"] = {
            "any": [{"fact": "applies", "op": "=", "value": True}, {"fact": "price", "op": ">=", "param": "p_material"}]
        }

    assert rubric(_variant(raw_f, m))["M"] == (
        "Carbon price applies to steel is Yes or Effective carbon price >= 10 USD/tCO2"
    )


def test_ac17_override_and_region(raw_f):
    def m(c):
        c["params"][0]["by_region"] = {"China": {"value": 40, "source": _src("cn")}}

    rules = _variant(raw_f, m)
    assert rubric(rules)["H"] == (
        "Effective carbon price >= 50 USD/tCO2 (China: 40 USD/tCO2) and Border levy in force is Yes"
    )
    assert render_group(rules.levels["H"], rules, region="China") == (
        "Effective carbon price >= 40 USD/tCO2 and Border levy in force is Yes"
    )
    assert render_group(rules.levels["H"], rules, region="United States") == (
        "Effective carbon price >= 50 USD/tCO2 and Border levy in force is Yes"
    )


def test_ac20_open_param(raw_f):
    rb = _rb6(copy.deepcopy(raw_f))
    assert rubric(_rules(rb))["H"] == "Effective carbon price >= [open: High price level] and Border levy in force is Yes"


def test_ac25_fact_vs_fact(raw_f):
    rb = _rb2(copy.deepcopy(raw_f))
    _stl(rb)["levels"]["H"] = {"all": [{"fact": "ren", "op": "<=", "other_fact": "fos"}]}
    assert rubric(_rules(rb))["H"] == "Renewable LCOE <= New-build fossil LCOE"


def test_unitless_computed_fact_and_param(raw_f):
    rb = _rb2(copy.deepcopy(raw_f))
    assert rubric(_rules(rb))["H"] == "LCOE ratio <= 1"


def test_percent_attaches_and_no_is_rendered(raw_f):
    def m(c):
        c["params"][0].update(value=100, unit="%")
        c["levels"]["H"] = {
            "all": [{"fact": "price", "op": ">=", "param": "p_high"}, {"fact": "levy", "op": "=", "value": False}]
        }

    assert rubric(_variant(raw_f, m))["H"] == "Effective carbon price >= 100% and Border levy in force is No"


def test_ac149_enum_in(raw_f):
    def m(c):
        c["facts"][1] = {
            "id": "scheme", "label": "Carbon pricing scheme", "type": "enum",
            "allowed_values": ["ETS", "tax", "none"], "definition": "d",
        }  # fmt: skip
        c["levels"]["M"] = {
            "all": [
                {"fact": "scheme", "op": "in", "value": ["ETS", "tax"]},
                {"fact": "price", "op": ">=", "param": "p_material"},
            ]
        }

    assert rubric(_variant(raw_f, m))["M"] == (
        "Carbon pricing scheme in ETS, tax and Effective carbon price >= 10 USD/tCO2"
    )


def test_ac153_date(raw_f):
    def m(c):
        c["facts"].append({"id": "start", "label": "Levy start date", "type": "date", "definition": "d"})
        c["levels"]["H"]["all"].append({"fact": "start", "op": "<=", "value": "2026-12-31"})

    assert rubric(_variant(raw_f, m))["H"] == (
        "Effective carbon price >= 50 USD/tCO2 and Border levy in force is Yes and Levy start date <= 2026-12-31"
    )


@pytest.mark.parametrize(
    "x, text",
    [(72.0, "72"), (9.366, "9.37"), (9.9988, "10"), (9.2991, "9.3"), (72.005, "72.01"), (0.75, "0.75")],
)
def test_fmt_number(x, text):
    assert fmt_number(x) == text


def test_markdown_deterministic_and_in_schema_order(fixture_dir, raw_f):  # noqa: F811
    rule_book, raw = load_rule_book(fixture_dir)
    schema = json.loads((fixture_dir / "criteria_schema.json").read_text(encoding="utf-8"))
    a = render_rule_book_md(rule_book, schema)
    assert a == render_rule_book_md(rule_book, schema)
    assert "## STL-R1 Effective carbon price on steel production incl. border adjustment" in a
    assert "Hydrogen-based direct reduced iron" in a
    assert "Price per tonne CO2 paid by steel producers" in a
    assert "Otherwise (neither H nor M holds)" in a
    assert "p_high" in a and "Fixture rationale for the high price level." in a and "https://example.org/p_high" in a

    # criteria appear in schema order, not rule-book order
    second = copy.deepcopy(schema["criteria"][0])
    second.update(code="STL-R0", criterion="Zeroth")
    schema["criteria"].append(second)
    raw["criteria"]["STL-R0"] = copy.deepcopy(raw["criteria"]["STL-R1"])
    raw["criteria"] = {k: raw["criteria"][k] for k in ("STL-R0", "STL-R1")}
    rule_book = type(rule_book).model_validate(raw)
    md = render_rule_book_md(rule_book, schema)
    assert md.index("## STL-R1 ") < md.index("## STL-R0 ")


def test_markdown_lists_open_question(raw_f, fixture_dir):  # noqa: F811
    rb = _rb6(copy.deepcopy(raw_f))
    rule_book = type(load_rule_book(fixture_dir)[0]).model_validate(rb)
    schema = json.loads((fixture_dir / "criteria_schema.json").read_text(encoding="utf-8"))
    assert "What price closes the cost gap?" in render_rule_book_md(rule_book, schema)
