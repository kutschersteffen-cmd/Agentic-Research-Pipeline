from __future__ import annotations

import csv
import hashlib
import random

import pytest

from arp.signal_lab.cutoffs import CutoffTable
from arp.signal_lab.inputs import data_version_for, load_inputs
from arp.signal_lab.methods.base import run_method, run_recipe
from arp.signal_lab.registry import Registry
from arp.storage.run_store import RunStore
from tests.test_signal_lab_registry import _recipe
from tests.test_signal_methods_base import _month_ends

DATES = _month_ends(40)
WINDOW_START = DATES[13]  # 13 months of history: momentum with skip needs 12 real returns, and the first row has none


def _write_prices(tmp_path) -> None:
    rng = random.Random(3)
    tickers = "ABCDEF"
    level = {t: 100.0 for t in tickers}
    with (tmp_path / "prices.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", *tickers])
        for d in DATES:
            for t in tickers:
                level[t] *= 1 + rng.gauss(0.01, 0.05)
            writer.writerow([d, *(level[t] for t in tickers)])


def _momentum_recipe(**kw):
    return _recipe(
        category="price_momentum", method="price_momentum", text_source=None,
        params={"formation_period_months": 12}, window_start=WINDOW_START, window_end=DATES[-1], **kw,
    )


def test_data_version_unchanged_without_history():
    old = hashlib.sha256("\n".join(["a", "b"]).encode())
    old.update(b"prices")
    old.update(b"one")
    old.update(b"two")
    got = data_version_for(["b", "a"], b"prices", {"y": b"two", "x": b"one"}, None)
    assert got == old.hexdigest()[:12]


def test_history_changes_the_data_version():
    without = data_version_for(["a"], b"p", {}, None)
    with_history = data_version_for(["a"], b"p", {}, DATES[0])
    assert with_history != without and len(with_history) == 12
    assert data_version_for(["a"], b"p", {}, DATES[1]) != with_history


def test_load_inputs_loads_prices_and_panels_from_the_history_start(tmp_path):
    _write_prices(tmp_path)
    recipe = _momentum_recipe()
    plain, plain_version = load_inputs(recipe, tmp_path / "prices.csv", panels={"p": tmp_path / "prices.csv"})
    hist, hist_version = load_inputs(
        recipe, tmp_path / "prices.csv", panels={"p": tmp_path / "prices.csv"}, history_from=DATES[0]
    )
    assert plain.prices.period_ends == DATES[13:] and plain.panels["p"].period_ends == DATES[13:]
    assert hist.prices.period_ends == DATES and hist.panels["p"].period_ends == DATES
    assert plain_version != hist_version


def test_history_after_window_start_raises(tmp_path):
    _write_prices(tmp_path)
    with pytest.raises(ValueError, match="after the window start"):
        load_inputs(_momentum_recipe(), tmp_path / "prices.csv", history_from=DATES[14])


def test_history_outside_the_price_file_raises(tmp_path):
    _write_prices(tmp_path)
    with pytest.raises(ValueError, match="history_from 2000-01-31 is outside the price file"):
        load_inputs(_momentum_recipe(), tmp_path / "prices.csv", history_from="2000-01-31")


def test_window_outside_price_file_raises(tmp_path):
    _write_prices(tmp_path)
    recipe = _momentum_recipe().model_copy(update={"window_end": "2099-12-31"})
    with pytest.raises(ValueError, match="outside the price file"):
        load_inputs(recipe, tmp_path / "prices.csv")


def test_history_feeds_methods_not_evidence(pg, tmp_path):
    _write_prices(tmp_path)
    recipe = _momentum_recipe()
    spec = {"method": "price_momentum", "params": recipe.params}
    plain, plain_version = load_inputs(recipe, tmp_path / "prices.csv")
    hist, hist_version = load_inputs(recipe, tmp_path / "prices.csv", history_from=DATES[0])

    # The first window month: no formation window without history, a real score with it.
    assert run_method(spec, plain).panel.values["A"][0] is None
    assert run_method(spec, hist).panel.values["A"][13] is not None

    kw = dict(cutoffs=CutoffTable(entries={}))
    plain_rec = run_recipe(recipe, plain, registry=Registry(RunStore(pg, tmp_path / "r1")), data_version=plain_version, **kw)
    hist_rec = run_recipe(recipe, hist, registry=Registry(RunStore(pg, tmp_path / "r2")), data_version=hist_version, **kw)

    (plain_w,), (hist_w,) = plain_rec.evidence.windows, hist_rec.evidence.windows
    assert plain_w.periods == hist_w.periods == len(DATES) - 13  # evidence months are the window's, history or not
    plain_dates, hist_dates = [d for d, _ in plain_w.series], [d for d, _ in hist_w.series]
    # History lets the method score earlier window months; it never adds a month before the window.
    assert hist_dates[0] == DATES[14] and plain_dates[0] == DATES[27]
    assert set(plain_dates) <= set(hist_dates) and hist_dates[-1] == DATES[-1]
    assert plain_rec.experiment_id != hist_rec.experiment_id


def test_history_from_must_be_a_price_file_date(tmp_path):
    _write_prices(tmp_path)
    # 2015-xx-15 loads the same rows as the month end after it, but would hash to a different experiment.
    off_grid = DATES[1][:8] + "15"
    with pytest.raises(ValueError, match=f"history_from {off_grid} is not one of the price file's dates"):
        load_inputs(_momentum_recipe(), tmp_path / "prices.csv", history_from=off_grid)
