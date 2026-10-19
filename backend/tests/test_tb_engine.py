from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from arp.transition_barrier import clock
from arp.transition_barrier.engine import Value, cell_evidence, cell_source, derive, fact_confidence
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
    return [val("ren", ren, "D1", 8, unit="USD/MWh"), val("fos", fos, *fos_doc, unit="USD/MWh")]


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


# --- rendered conditions, clauses and details -------------------------------------------

D1, D2, D3 = (DOCS[d][0] for d in ("D1", "D2", "D3"))
H_SENTENCE = "H: Effective carbon price >= 50 USD/tCO2 and Border levy in force is Yes."
PRICE_72 = f"Effective carbon price = 72 USD/tCO2 ({D1}, p. 12): pass."
LEVY_YES = f"Border levy in force = Yes ({D2}, p. 3): pass."


def clause(result, level="H", i=0):
    return result.levels[level].conditions[i].clause


def lcoe_rules(formula, p_parity, unit):
    raw = rb_variant(2).model_dump()
    next(f for f in raw["facts"] if f["id"] == "ratio")["formula"] = formula
    next(p for p in raw["params"] if p["id"] == "p_parity").update(value=p_parity, unit=unit)
    return CriterionRules.model_validate(raw)


def test_ac7():
    r = run(rb_variant(1), defaults())
    assert r.levels["H"].detail == f"{H_SENTENCE} {PRICE_72} {LEVY_YES}"


def test_ac8():
    r = run(rb_variant(1), defaults(levy=None))
    assert r.levels["H"].detail.endswith("Border levy in force not found: unknown.")


def test_ac10():
    snapshot = json.loads(FIXTURE_RB.read_text(encoding="utf-8"))["criteria"]["STL-R1"]
    r = derive(rb_variant(1), EU, defaults(), rule_book_version=7, run_id="run-9", snapshot=snapshot)
    assert (r.rule_book_version, r.run_id, r.snapshot) == (7, "run-9", snapshot)


def test_condition_text_and_level_sentence_apply_the_region():
    r = run(rb_variant(5), defaults(price=val("price", 45, "D1", 14)), region=CN)
    assert r.levels["H"].conditions[0].text == "Effective carbon price >= 40 USD/tCO2"
    assert r.levels["H"].text == "Effective carbon price >= 40 USD/tCO2 and Border levy in force is Yes"


def test_ac143():
    r = run(rb_variant(5), defaults(price=val("price", 45, "D1", 14)), region=CN)
    assert r.levels["H"].detail.startswith(
        f"H: Effective carbon price >= 40 USD/tCO2 and Border levy in force is Yes. "
        f"Effective carbon price = 45 USD/tCO2 ({D1}, p. 14): pass."
    )


def test_ac21():
    r = run(rb_variant(2), defaults() + lcoe())
    assert clause(r) == (
        f"LCOE ratio = 0.75 from Renewable LCOE = 45 USD/MWh ({D1}, p. 8) "
        f"and New-build fossil LCOE = 60 USD/MWh ({D1}, p. 9): pass."
    )


def test_ac24():
    r = run(rb_variant(8), defaults() + lcoe())
    assert clause(r) == (f"Renewable LCOE = 45 USD/MWh ({D1}, p. 8) vs New-build fossil LCOE = 60 USD/MWh ({D1}, p. 9): pass.")


def test_ac146_percent_attaches_without_space():
    r = run(lcoe_rules("ratio_pct", 100, "%"), defaults() + lcoe())
    assert clause(r).startswith("LCOE ratio = 75% from")


def test_ac147_difference_keeps_the_inputs_unit():
    r = run(lcoe_rules("difference", 0, "USD/MWh"), defaults() + lcoe())
    assert clause(r).startswith("LCOE ratio = -15 USD/MWh from")


def test_ac35_rounds_half_up_to_two_decimals():
    r = run(rb_variant(1), defaults(price=val("price", 72.005, "D1", 15)))
    assert clause(r) == f"Effective carbon price = 72.01 USD/tCO2 ({D1}, p. 15): pass."


def test_ac38_clause():
    r = run(rb_variant(1), defaults(price=None) + [val("price", 72), val("price", 65, "D3", 7)])
    assert clause(r) == f"Effective carbon price = 72 USD/tCO2 ({D1}, p. 12), 65 USD/tCO2 ({D3}, p. 7): pass."


def test_ac40_mixed_clause():
    r = run(rb_variant(1), defaults(price=None, levy=val("levy", False)) + [val("price", 72), val("price", 30, "D3", 7)])
    assert clause(r) == f"Effective carbon price = 72 USD/tCO2 ({D1}, p. 12), 30 USD/tCO2 ({D3}, p. 7): mixed."


def test_ac45_clause():
    applies = val("applies", True, confidence="low", machine_checked=False, entered_by="a.analyst")
    r = run(rb_variant(1), defaults(applies=applies))
    assert clause(r, "M") == f"Carbon price applies to steel = Yes ({D1}, entered by a.analyst): pass."


def test_locator_without_page():
    r = run(rb_variant(1), defaults(levy=val("levy", True, "D2", None, locator="Art. 36")))
    assert clause(r, "H", 1) == f"Border levy in force = Yes ({D2}, Art. 36): pass."


def test_nested_groups_contribute_their_leaves_in_order():
    r = run(rb_variant(4), defaults(price=val("price", 30)))
    assert [c.text for c in r.levels["M"].conditions] == [
        "Carbon price applies to steel is Yes",
        "Effective carbon price >= 10 USD/tCO2",
        "Border levy in force is Yes",
    ]


def test_values_entries_are_json_ready_and_carry_shown_and_extracted():
    start = val("start", date(2026, 1, 1), "D2", 3, document_id=2)
    r = run(rb_variant(10), defaults() + [start])
    entries = {e["fact"]: e for e in r.values}
    json.dumps(r.values)
    assert (entries["start"]["value"], entries["start"]["shown"], entries["start"]["document_id"]) == (
        "2026-01-01",
        "2026-01-01",
        2,
    )
    assert (entries["price"]["shown"], entries["price"]["extracted"]) == ("72 USD/tCO2", "72 USD/tCO2")
    assert entries["applies"]["shown"] == "Yes"
    assert entries["price"]["id"] and entries["price"]["page"] == 12


def test_computed_entry_has_no_document():
    r = run(rb_variant(2), defaults() + lcoe())
    ratio = next(v for v in r.values if v["fact"] == "ratio")
    assert (ratio["document"], ratio["page"], ratio["shown"]) == (None, None, "0.75")


def test_ac59_evidence():
    r = run(rb_variant(1), defaults(price=val("price", 30)))
    assert cell_evidence(r) == (
        f"{H_SENTENCE} Effective carbon price = 30 USD/tCO2 ({D1}, p. 13): fail. {LEVY_YES} "
        f"M: Carbon price applies to steel is Yes and Effective carbon price >= 10 USD/tCO2. "
        f"Carbon price applies to steel = Yes ({D1}, p. 4): pass. "
        f"Effective carbon price = 30 USD/tCO2 ({D1}, p. 13): pass."
    )


def test_evidence_is_only_h_when_h_did_not_fail():
    r = run(rb_variant(1), defaults())
    assert cell_evidence(r) == r.levels["H"].detail


def test_ac58_source():
    r = run(rb_variant(1), defaults(price=val("price", 30)))
    assert cell_source(r, rb_variant(1)) == f"{D1}; {D2}"


def test_source_follows_fact_order_and_skips_uncounted():
    gone = val("price", 72, counted=False, reason="Quote not found in source")
    r = run(rb_variant(1), defaults(price=gone, applies=val("applies", True, "D3", 8)))
    assert cell_source(r, rb_variant(1)) == f"{D3}; {D2}"
