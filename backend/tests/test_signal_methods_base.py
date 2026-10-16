from __future__ import annotations

import calendar
import random

import pytest

from arp.replication.characteristics_data import CharacteristicPanel
from arp.replication.price_data import PricePanel
from arp.signal_lab.cutoffs import CutoffTable
from arp.signal_lab.methods import base
from arp.signal_lab.methods.base import MethodInput, MethodResult, run_method, run_recipe, text_buckets
from arp.signal_lab.methods.checks import lookahead_violations
from arp.signal_lab.registry import SIGNAL_REGISTRY_RUN_ID, Registry
from arp.signal_lab.text_store import make_record
from arp.storage.run_store import RunStore
from tests.test_signal_lab_registry import _evidence, _recipe


def _month_ends(n: int) -> list[str]:
    out = []
    for m in range(n):
        y, mo = 2018 + m // 12, m % 12 + 1
        out.append(f"{y}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}")
    return out


def _prices(n: int = 30) -> PricePanel:
    rng = random.Random(7)
    returns = {t: [None] + [rng.gauss(0.01, 0.05) for _ in range(n - 1)] for t in "ABCDEF"}
    return PricePanel(period_ends=_month_ends(n), returns=returns, source="test")


def _text(issuer: str | None, when: str):
    return make_record(
        source="tr_news", source_item_id=f"{issuer}{when}", company_id=issuer,
        event_time=when, knowledge_time=when, title="t", body="b",
    )


def test_text_buckets_follow_month_ends():
    items = [
        _text("A", "2020-01-31T23:59:59Z"),
        _text("A", "2020-02-01T00:00:00Z"),
        _text("A", "2019-12-31T23:59:59Z"),  # before the grid's first calendar month
        _text("A", "2020-03-01T00:00:00Z"),  # after the last bucket
        _text(None, "2020-01-15T00:00:00Z"),  # unlinked
    ]
    got = text_buckets(items, ["2020-01-31", "2020-02-29"])
    assert list(got) == ["A"]
    assert [[t.event_time for t in b] for b in got["A"]] == [["2020-01-31T23:59:59Z"], ["2020-02-01T00:00:00Z"]]


def test_unknown_method_lists_known_names():
    with pytest.raises(ValueError, match="nope.*price_momentum"):
        base.get_method("nope")


def test_panel_method_missing_name_raises():
    inp = MethodInput(texts=[], prices=_prices(3))
    with pytest.raises(ValueError, match="missing"):
        run_method({"method": "panel", "params": {"name": "missing"}}, inp)


def _peeking(params: dict, inp: MethodInput) -> MethodResult:
    vals = {t: r[1:] + [None] for t, r in inp.prices.returns.items()}
    return MethodResult(CharacteristicPanel(list(inp.prices.period_ends), vals, "peek"))


def test_lookahead_violations_catches_a_peeking_method(monkeypatch):
    inp = MethodInput(texts=[], prices=_prices(8))
    monkeypatch.setitem(base._METHODS, "peeking", _peeking)
    assert lookahead_violations({"method": "peeking", "params": {}}, inp)
    spec = {"method": "price_momentum", "params": {"formation_period_months": 3}}
    assert lookahead_violations(spec, inp) == []


@pytest.fixture
def registry(pg, tmp_path) -> Registry:
    return Registry(RunStore(pg, tmp_path / "runs"))


def test_run_recipe_registers_and_counts_trials(registry, monkeypatch):
    inp = MethodInput(texts=[], prices=_prices())
    recipe = _recipe(
        category="price_momentum", method="price_momentum", text_source=None,
        params={"formation_period_months": 3}, window_start="2018-01-31", window_end="2020-06-30",
    )
    kw = dict(registry=registry, cutoffs=CutoffTable(entries={}), data_version="v1")
    first = run_recipe(recipe, inp, **kw)
    second = run_recipe(recipe, inp, **kw)
    assert first.experiment_id == second.experiment_id
    assert len(registry.list_experiments()) == 1
    assert second.evidence.n_trials == 1

    def short(params: dict, inp: MethodInput) -> MethodResult:
        return MethodResult(CharacteristicPanel(inp.prices.period_ends[:-1], {"A": [0.0] * 29}, "short"))

    monkeypatch.setitem(base._METHODS, "short", short)
    with pytest.raises(ValueError, match="grid"):
        run_recipe(recipe.model_copy(update={"method": "short"}), inp, **kw)


def test_register_stores_notes_and_old_rows_still_load(registry):
    rec = registry.register(
        _recipe(), _evidence(), data_version="v1", model=None, cutoff=None, notes={"k": [1, 2]}
    )
    assert rec.notes == {"k": [1, 2]}
    assert registry.list_experiments()[0].notes == {"k": [1, 2]}

    row = {"type": "experiment", "_key": "experiment:old", **rec.model_dump(mode="json"), "experiment_id": "old"}
    del row["notes"]
    registry.store.append_result(SIGNAL_REGISTRY_RUN_ID, row)
    assert next(r for r in registry.list_experiments() if r.experiment_id == "old").notes == {}
