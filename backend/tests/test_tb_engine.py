from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from arp.transition_barrier import clock
from arp.transition_barrier.engine import Value, derive, fact_confidence
from arp.transition_barrier.rule_book import CriterionRules

FIXTURE_RB = Path(__file__).parent / "fixtures" / "transition_barrier" / "rule_book.json"
TODAY = date(2026, 10, 20)
EU, CN = "European Union", "China"

# title, tier, as-of date
DOCS = {
    "D1": ("EU ETS Market Report 2026", "primary", date(2026, 3, 31)),
    "D2": ("CBAM Regulation 2023/956", "primary", date(2023, 5, 16)),
    "D3": ("Steel Policy Tracker", "secondary", date(2026, 6, 30)),
}
MAX_AGE = {"price": 365}
DEFAULT_CITE = {"price": ("D1", 12), "applies": ("D1", 4), "levy": ("D2", 3)}


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: TODAY)


# --- rule books -------------------------------------------------------------------------


def _param(pid, label, value, unit, **extra):
    return {
        "id": pid,
        "label": label,
        "value": value,
        "unit": unit,
        "by_region": {},
        "rationale": "Fixture rationale.",
        "source": {"title": "Fixture source", "url": "https://example.org/p", "locator": "Table 1"},
        **extra,
    }


def _leaf(fact, op, **rhs):
    return {"fact": fact, "op": op, **rhs}


def rb_variant(n: int) -> CriterionRules:
    """RB (n = 1) or its variants RB2-RB10 as the spec's Fixtures section describes them."""
    raw = json.loads(FIXTURE_RB.read_text(encoding="utf-8"))["criteria"]["STL-R1"]
    facts = {f["id"]: f for f in raw["facts"]}
    params = {p["id"]: p for p in raw["params"]}
    levels = raw["levels"]
    if n in (2, 8):
        raw["facts"] += [
            {"id": "ren", "label": "Renewable LCOE", "type": "number", "unit": "USD/MWh"},
            {"id": "fos", "label": "New-build fossil LCOE", "type": "number", "unit": "USD/MWh"},
            {"id": "ratio", "label": "LCOE ratio", "formula": "ratio", "inputs": ["ren", "fos"]},
        ]
        raw["params"].append(_param("p_parity", "Parity level", 1, None))
        levels["H"] = {"all": [_leaf("ratio", "<=", param="p_parity")]}
    if n == 3:
        levels["M"] = {"any": [_leaf("applies", "=", value=True), _leaf("price", ">=", param="p_material")]}
    if n == 4:
        levels["M"] = {
            "all": [
                _leaf("applies", "=", value=True),
                {"any": [_leaf("price", ">=", param="p_material"), _leaf("levy", "=", value=True)]},
            ]
        }
    if n == 5:
        params["p_high"]["by_region"] = {"China": {"value": 40, "source": {"title": "Fixture source"}}}
    if n == 6:
        params["p_high"].update(value=None, status="open", question="What is high?")
    if n == 7:
        params["p_material"].update(value=None, status="open", question="What is material?")
    if n == 8:
        levels["H"] = {"all": [_leaf("ren", "<=", other_fact="fos")]}
    if n == 9:
        raw["facts"][raw["facts"].index(facts["applies"])] = {
            "id": "scheme",
            "label": "Carbon pricing scheme",
            "type": "enum",
            "allowed_values": ["ETS", "tax", "none"],
        }
        levels["M"] = {"all": [_leaf("scheme", "in", value=["ETS", "tax"]), _leaf("price", ">=", param="p_material")]}
    if n == 10:
        raw["facts"].append({"id": "start", "label": "Levy start date", "type": "date"})
        levels["H"]["all"].append(_leaf("start", "<=", value="2026-12-31"))
    return CriterionRules.model_validate(raw)


# --- values -----------------------------------------------------------------------------

_ids = iter(range(1, 10_000))


def val(fact, value, doc=None, page=None, **kw) -> Value:
    if doc is None:
        doc, page = DEFAULT_CITE[fact]
        if fact == "price" and value == 30:
            doc, page = "D1", 13
        if fact == "price" and value == 9:
            doc, page = "D3", 9
    title, tier, as_of = DOCS[doc]
    fields = dict(
        id=f"v{next(_ids)}",
        fact=fact,
        value=value,
        unit="USD/tCO2" if fact == "price" else None,
        document=title,
        page=page,
        locator=None,
        confidence=fact_confidence(tier, as_of, MAX_AGE.get(fact), TODAY, True),
        machine_checked=True,
    )
    return Value(**{**fields, **kw})


def defaults(**overrides) -> list[Value]:
    """The default counted values; a fact given in `overrides` is replaced (None removes it)."""
    base = {"price": val("price", 72), "applies": val("applies", True), "levy": val("levy", True)}
    for fact, v in overrides.items():
        base.pop(fact)
        if v is not None:
            base[fact] = v
    return list(base.values())


def run(rules, values, region=EU, **kw):
    return derive(rules, region, values, rule_book_version=7, run_id="run-1", snapshot={"s": 1}, **kw)


def outcomes(result, level):
    return [c.outcome for c in result.levels[level].conditions]


# --- engine -----------------------------------------------------------------------------


def test_ac1_and_ac10():
    r = run(rb_variant(1), defaults())
    assert r.rating == "H"
    assert outcomes(r, "H") == ["pass", "pass"]
    assert r.levels["H"].outcome == "pass"
    assert r.confidence == "high"
    assert (r.rule_book_version, r.run_id, r.snapshot) == (7, "run-1", {"s": 1})


def test_ac2():
    r = run(rb_variant(1), defaults(price=val("price", 30)))
    assert r.rating == "M"
    assert r.levels["H"].outcome == "fail"


def test_ac3():
    r = run(rb_variant(1), defaults(price=val("price", 9), levy=val("levy", False)))
    assert r.rating == "L"


def test_ac4():
    r = run(rb_variant(1), defaults(price=None))
    assert r.rating == "not_rated"
    assert r.missing_facts == ["Effective carbon price"]
    assert r.open_params == []


def test_ac5():
    assert run(rb_variant(1), defaults(price=val("price", 30), levy=None)).rating == "M"


def test_ac6():
    r = run(rb_variant(1), defaults(levy=None))
    assert r.rating == "not_rated"
    assert r.missing_facts == ["Border levy in force"]


def test_ac12():
    assert run(rb_variant(3), defaults(price=val("price", 30), applies=None)).rating == "M"


def test_missing_fact_that_cannot_change_the_rating_is_not_named():
    # RB4: M = all(applies, any(price >= p_material, levy)); the any already passes on price = 30.
    r = run(rb_variant(4), defaults(price=val("price", 30), applies=None, levy=None))
    assert r.rating == "not_rated"
    assert r.missing_facts == ["Carbon price applies to steel"]


def test_ac13():
    r = run(rb_variant(3), defaults(price=val("price", 9), applies=None))
    assert r.rating == "not_rated"
    assert r.missing_facts == ["Carbon price applies to steel"]


def test_ac15():
    r = run(rb_variant(5), defaults(price=val("price", 45, "D1", 14)), region=CN)
    assert r.rating == "H"


def test_ac16():
    assert run(rb_variant(5), defaults(price=val("price", 45, "D1", 14)), region=EU).rating == "M"


def test_ac18_result():
    r = run(rb_variant(6), defaults())
    assert r.rating == "not_rated"
    assert r.open_params == ["High price level"]
    assert r.missing_facts == []


def test_ac19_result():
    r = run(rb_variant(7), defaults())
    assert r.rating == "H"
    assert r.open_params == []


def lcoe(ren=45, fos=60, fos_doc=("D1", 9)):
    return [val("ren", ren, "D1", 8), val("fos", fos, *fos_doc)]


def test_ac22():
    r = run(rb_variant(2), defaults() + [val("ren", 45, "D1", 8)])
    assert r.rating == "not_rated"
    assert r.missing_facts == ["New-build fossil LCOE"]


def test_ac23():
    r = run(rb_variant(2), defaults() + lcoe(fos_doc=("D3", 12)))
    ratio = next(v for v in r.values if v["fact"] == "ratio")
    assert (ratio["value"], ratio["confidence"]) == (0.75, "medium")
    assert r.rating == "H"


def test_division_by_zero():
    r = run(rb_variant(2), defaults() + lcoe(fos=0))
    assert r.rating == "not_rated"
    ratio = next(v for v in r.values if v["fact"] == "ratio")
    assert (ratio["counted"], ratio["reason"]) == (False, "Division by zero")


def test_fact_to_fact_comparison():
    assert run(rb_variant(8), defaults() + lcoe()).rating == "H"


def test_ac150():
    assert run(rb_variant(9), defaults(applies=None, price=val("price", 30)) + [val("scheme", "ETS", "D1", 20)]).rating == "M"


def test_ac151():
    r = run(rb_variant(9), defaults(applies=None, price=val("price", 30)) + [val("scheme", "none", "D3", 14)])
    assert r.rating == "L"


def test_ac152():
    r = run(rb_variant(9), defaults(applies=None, price=val("price", 30)))
    assert r.rating == "not_rated"
    assert r.missing_facts == ["Carbon pricing scheme"]


def test_ac154():
    assert run(rb_variant(10), defaults() + [val("start", date(2026, 1, 1), "D2", 3)]).rating == "H"


def test_ac36_conflict():
    r = run(rb_variant(1), defaults(price=None) + [val("price", 72), val("price", 30, "D3", 7)])
    assert r.rating == "conflict"


def test_ac38_rating():
    r = run(rb_variant(1), defaults(price=None) + [val("price", 72), val("price", 65, "D3", 7)])
    assert r.rating == "H"
    assert outcomes(r, "H") == ["pass", "pass"]


def test_ac39():
    r = run(rb_variant(1), defaults(price=None) + [val("price", 72), val("price", 65, "D3", 7)])
    assert r.confidence == "medium"


def test_ac40_rating():
    r = run(rb_variant(1), defaults(price=None, levy=val("levy", False)) + [val("price", 72), val("price", 30, "D3", 7)])
    assert r.rating == "M"
    assert r.levels["H"].outcome == "fail"
    assert outcomes(r, "H") == ["mixed", "fail"]


def test_ac41():
    r = run(rb_variant(1), defaults(price=None, levy=None) + [val("price", 72), val("price", 30, "D3", 7)])
    assert r.rating == "not_rated"
    assert r.missing_facts == ["Border levy in force"]


def test_ac42():
    r = run(rb_variant(1), defaults(levy=val("levy", True, "D3", 13)))
    assert r.rating == "H"
    assert r.confidence == "medium"


def test_ac43_ac44_fact_confidence():
    today = clock.today()
    assert fact_confidence("primary", date(2025, 9, 1), 365, today, True) == "medium"
    assert fact_confidence("primary", date(2025, 10, 20), 365, today, True) == "high"
    assert fact_confidence("primary", date(2020, 1, 1), None, today, True) == "high"
    assert fact_confidence("secondary", date(2026, 6, 30), None, today, True) == "medium"
    assert fact_confidence("primary", date(2026, 3, 31), 365, today, False) == "low"


def test_ac45_result():
    applies = val("applies", True, confidence="low", machine_checked=False, entered_by="a.analyst")
    r = run(rb_variant(1), defaults(applies=applies))
    assert (r.rating, r.confidence) == ("H", "low")
    entry = next(v for v in r.values if v["fact"] == "applies")
    assert (entry["machine_checked"], entry["entered_by"]) == (False, "a.analyst")


def test_uncounted_values_are_ignored():
    gone = val("price", 72, counted=False, reason="Quote not found in source")
    r = run(rb_variant(1), defaults(price=gone))
    assert r.rating == "not_rated"
    assert r.missing_facts == ["Effective carbon price"]
    assert any(v["reason"] == "Quote not found in source" for v in r.values)


def test_combination_cap():
    many = [val(f, v) for f, v in (("price", 72.0), ("applies", True), ("levy", True)) for _ in range(11)]
    r = run(copy.deepcopy(rb_variant(1)), many)
    assert r.rating == "conflict"
    assert r.notes == ["Too many value combinations (1331)"]
