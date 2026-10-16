from __future__ import annotations

import calendar
import random
import statistics

import pytest

from arp.replication.characteristics_data import CharacteristicPanel
from arp.replication.price_data import PricePanel
from arp.signal_lab.methods import base
from arp.signal_lab.methods.base import MethodInput, MethodResult, run_method
from arp.signal_lab.methods.checks import lookahead_violations
from arp.signal_lab.methods.transforms import apply_step


def _month_ends(n: int) -> list[str]:
    return [
        f"{2018 + m // 12}-{m % 12 + 1:02d}-{calendar.monthrange(2018 + m // 12, m % 12 + 1)[1]:02d}" for m in range(n)
    ]


def _panel(values: dict[str, list[float | None]]) -> CharacteristicPanel:
    n = len(next(iter(values.values())))
    return CharacteristicPanel(_month_ends(n), values, "test")


def _inp(panels: dict[str, CharacteristicPanel], n: int = 4) -> MethodInput:
    prices = PricePanel(_month_ends(n), {t: [None] + [0.01] * (n - 1) for t in "ABC"}, "test")
    return MethodInput(texts=[], prices=prices, panels=panels)


def _ref(name: str) -> dict:
    return {"method": "panel", "params": {"name": name}}


def test_change_leaves_the_first_lag_months_none():
    p = _panel({"A": [1.0, 3.0, None, 7.0], "B": [1.0, 1.0, 1.0, 1.0], "C": [0.0, 1.0, 2.0, 4.0]})
    one = apply_step(p, {"op": "change"}).values
    assert one["A"] == [None, 2.0, None, None]
    assert one["C"] == [None, 1.0, 1.0, 2.0]
    assert apply_step(p, {"op": "change", "lag": 2}).values["C"] == [None, None, 2.0, 3.0]


def test_decay_weights_available_past_values():
    p = _panel({"A": [1.0, 2.0, 4.0], "B": [None, 2.0, 4.0], "C": [1.0, None, 4.0]})
    got = apply_step(p, {"op": "decay", "half_life_months": 1}).values
    assert got["A"][2] == pytest.approx((4 + 2 * 0.5 + 1 * 0.25) / 1.75)
    assert got["B"][2] == pytest.approx((4 + 2 * 0.5) / 1.5)
    assert got["C"][2] == pytest.approx((4 + 1 * 0.25) / 1.25)
    assert got["B"][0] is None and got["C"][1] is None  # x_i itself missing


def test_zscore_has_mean_zero_and_none_when_degenerate():
    p = _panel({"A": [1.0, 5.0, 1.0], "B": [2.0, 5.0, None], "C": [6.0, 5.0, 3.0]})
    got = apply_step(p, {"op": "zscore"}).values
    col = [got[t][0] for t in "ABC"]
    assert sum(col) == pytest.approx(0.0)
    assert statistics.pstdev(col) == pytest.approx(1.0)
    assert [got[t][1] for t in "ABC"] == [None] * 3  # zero spread
    assert [got[t][2] for t in "ABC"] == [None] * 3  # only 2 names


@pytest.mark.parametrize("op", ["zscore", "rank"])
def test_constant_float_column_is_none(op):
    # std() of a constant 0.1 column is rounding noise, not 0.0.
    p = _panel({"A": [0.1, 1.0], "B": [0.1, 2.0], "C": [0.1, 3.0]})
    got = apply_step(p, {"op": op}).values
    assert [got[t][0] for t in "ABC"] == [None] * 3
    assert got["A"][1] is not None


def test_rank_is_average_rank_percentile():
    p = _panel({"A": [10.0, 1.0], "B": [20.0, 1.0], "C": [30.0, 2.0]})
    got = apply_step(p, {"op": "rank"}).values
    assert [got[t][0] for t in "ABC"] == pytest.approx([1 / 3, 2 / 3, 1.0])
    assert [got[t][1] for t in "ABC"] == pytest.approx([1.5 / 3, 1.5 / 3, 1.0])


def test_mean_last_needs_every_value():
    p = _panel({"A": [1.0, 2.0, 3.0, 4.0], "B": [1.0, None, 3.0, 5.0], "C": [0.0] * 4})
    got = apply_step(p, {"op": "mean_last", "months": 2}).values
    assert got["A"] == [None, 1.5, 2.5, 3.5]
    assert got["B"] == [None, None, None, 4.0]


def test_unknown_op_and_bad_params_raise_value_error():
    p = _panel({"A": [1.0, 2.0]})
    with pytest.raises(ValueError, match="unknown"):
        apply_step(p, {"op": "nope"})
    with pytest.raises(ValueError, match="lag"):
        apply_step(p, {"op": "change", "lag": 0})
    with pytest.raises(ValueError, match="half_life"):
        apply_step(p, {"op": "decay"})
    with pytest.raises(ValueError, match="months"):
        apply_step(p, {"op": "mean_last", "months": 0})


def _model_method(model: str, values: dict[str, list[float | None]]):
    def fn(params: dict, inp: MethodInput) -> MethodResult:
        return MethodResult(CharacteristicPanel(list(inp.prices.period_ends), values, model), model=model)

    return fn


def test_transform_keeps_the_base_model(monkeypatch):
    monkeypatch.setitem(base._METHODS, "modelled", _model_method("m1", {"A": [1.0, 2.0, 3.0, 4.0]}))
    spec = {"method": "transform", "params": {"base": {"method": "modelled", "params": {}}, "steps": [{"op": "change"}]}}
    res = run_method(spec, _inp({}))
    assert res.model == "m1"
    assert res.panel.values["A"] == [None, 1.0, 1.0, 1.0]
    plain = {"method": "transform", "params": {"base": _ref("x"), "steps": []}}
    assert run_method(plain, _inp({"x": _panel({"A": [1.0] * 4})})).model is None


def _components() -> dict[str, CharacteristicPanel]:
    return {
        "a": _panel({"A": [1.0, 3.0, 1.0, 1.0], "B": [2.0, 2.0, 2.0, 2.0], "C": [3.0, 1.0, 3.0, 3.0], "D": [4.0] * 4}),
        "b": _panel({"A": [10.0, 10.0, 10.0, None], "B": [20.0, 30.0, 20.0, 20.0], "C": [30.0, 20.0, 30.0, 30.0], "D": [40.0] * 4}),
    }


def _composite(**params) -> dict:
    return {"method": "composite", "params": {"components": [_ref("a"), _ref("b")], **params}}


def test_composite_ranks_then_averages():
    got = run_method(_composite(), _inp(_components())).panel.values
    assert got["A"][0] == pytest.approx(0.25)
    assert got["C"][1] == pytest.approx((1 / 4 + 2 / 4) / 2)
    weighted = run_method(_composite(weights=[3, 1]), _inp(_components())).panel.values
    assert weighted["C"][1] == pytest.approx((3 * 1 / 4 + 2 / 4) / 4)


def test_composite_is_none_when_a_component_is_missing():
    got = run_method(_composite(), _inp(_components())).panel.values
    assert got["A"][3] is None  # b has no value for A in month 3
    assert got["B"][3] == pytest.approx((2 / 4 + 1 / 3) / 2)


def test_composite_min_components_relaxes_it():
    got = run_method(_composite(min_components=1), _inp(_components())).panel.values
    assert got["A"][3] == pytest.approx(0.25)  # only a's rank is present


def test_composite_bad_params_raise_value_error():
    with pytest.raises(ValueError, match="weights"):
        run_method(_composite(weights=[1.0]), _inp(_components()))
    with pytest.raises(ValueError, match="min_components"):
        run_method(_composite(min_components=3), _inp(_components()))
    with pytest.raises(ValueError, match="weights"):
        run_method(_composite(weights=[]), _inp(_components()))
    with pytest.raises(ValueError, match="min_components"):
        run_method(_composite(min_components=0), _inp(_components()))
    with pytest.raises(ValueError, match="at least one component"):
        run_method({"method": "composite", "params": {"components": []}}, _inp({}))


def test_composite_of_two_models_raises(monkeypatch):
    monkeypatch.setitem(base._METHODS, "m1", _model_method("m1", {"A": [1.0] * 4}))
    monkeypatch.setitem(base._METHODS, "m2", _model_method("m2", {"A": [1.0] * 4}))
    spec = {"method": "composite", "params": {"components": [{"method": "m1"}, {"method": "m2"}]}}
    with pytest.raises(ValueError, match="composite of different models is not supported"):
        run_method(spec, _inp({}))
    # A model-free component next to a model is fine and keeps the model.
    ok = {"method": "composite", "params": {"components": [{"method": "m1"}, _ref("a")]}}
    assert run_method(ok, _inp(_components())).model == "m1"


def test_transforms_and_composite_have_no_lookahead():
    rng = random.Random(3)
    n = 14
    returns = {t: [None] + [rng.gauss(0.01, 0.05) for _ in range(n - 1)] for t in "ABCDE"}
    prices = PricePanel(_month_ends(n), returns, "test")
    ends = prices.period_ends
    panels = {
        k: CharacteristicPanel(ends, {t: [rng.random() for _ in range(n)] for t in "ABCDE"}, k) for k in ("x", "y")
    }
    inp = MethodInput(texts=[], prices=prices, panels=panels)
    mom = {"method": "price_momentum", "params": {"formation_period_months": 3}}
    steps = [{"op": "change", "lag": 2}, {"op": "decay", "half_life_months": 2}, {"op": "zscore"},
             {"op": "rank"}, {"op": "mean_last", "months": 3}]
    assert lookahead_violations({"method": "transform", "params": {"base": mom, "steps": steps}}, inp) == []
    comp = {"method": "composite", "params": {"components": [_ref("x"), _ref("y")]}}
    assert lookahead_violations(comp, inp) == []
