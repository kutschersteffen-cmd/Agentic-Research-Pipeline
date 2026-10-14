from __future__ import annotations

import numpy as np
import pytest

from arp.replication.characteristics_data import CharacteristicPanel
from arp.replication.price_data import PricePanel
from arp.signal_lab.baselines import momentum_panel
from arp.signal_lab.cutoffs import CutoffTable, ModelCutoff
from arp.signal_lab.evidence import evaluate_signal, sentiment_spec

N_MONTHS = 60
TICKERS = [f"T{i}" for i in range(20)]
DATES = [f"{2020 + m // 12}-{m % 12 + 1:02d}-28" for m in range(N_MONTHS)]
CUTOFF_IDX = 29  # DATES[29] == 2022-06-28
MODEL = "m1"
TABLE = CutoffTable(entries={MODEL: ModelCutoff(cutoff=DATES[CUTOFF_IDX], source="test")})
SPEC = sentiment_spec("sent", start=DATES[0], end=DATES[-1])


def _data(*, noise: float = 0.5, informative_until: int = N_MONTHS):
    rng = np.random.default_rng(1)
    rets = rng.normal(0.01, 0.05, (N_MONTHS, len(TICKERS)))
    sc = np.zeros_like(rets)
    for m in range(N_MONTHS - 1):
        sig = rets[m + 1] if m < informative_until else rng.normal(0, 0.05, len(TICKERS))
        sc[m] = sig + rng.normal(0, 0.05 * noise, len(TICKERS))
    prices = PricePanel(
        period_ends=DATES, returns={t: [float(rets[m, k]) for m in range(N_MONTHS)] for k, t in enumerate(TICKERS)}, source="t"
    )
    scores = CharacteristicPanel(
        period_ends=DATES, values={t: [float(sc[m, k]) for m in range(N_MONTHS)] for k, t in enumerate(TICKERS)}, source="t"
    )
    return scores, prices


def _eval(scores, prices, **kw):
    kw.setdefault("model", MODEL)
    return evaluate_signal(scores, prices, SPEC, cutoffs=TABLE, **kw)


def test_unknown_model_has_only_in_window_evidence():
    scores, prices = _data()
    report = _eval(scores, prices, model="unknown")
    assert [w.window for w in report.windows] == ["in_window"]
    assert report.contamination_gap_ic is None


def test_no_model_is_all_post_cutoff():
    scores, prices = _data()
    report = _eval(scores, prices, model=None)
    assert [w.window for w in report.windows] == ["post_cutoff"]


def test_split_at_cutoff():
    scores, prices = _data()
    report = _eval(scores, prices)
    by = {w.window: w for w in report.windows}
    assert set(by) == {"in_window", "post_cutoff"}
    assert by["in_window"].periods == CUTOFF_IDX + 1
    assert by["post_cutoff"].periods == N_MONTHS - CUTOFF_IDX - 1
    assert by["in_window"].periods + by["post_cutoff"].periods == N_MONTHS
    assert by["in_window"].ic.mean > 0.5
    assert by["in_window"].net_long_short is not None
    assert by["in_window"].deflated_sharpe is not None


def test_return_month_follows_formation_month():
    scores, prices = _data()
    seen: dict[str, set[str]] = {}
    import arp.signal_lab.evidence as ev

    real = ev.run_backtest

    def spy(*a, **kw):
        seen[kw["period_label"]] = set(kw["allowed_period_ends"])
        return real(*a, **kw)

    ev.run_backtest = spy
    try:
        _eval(scores, prices)
    finally:
        ev.run_backtest = real
    # Last in-window score month's return month is the first month after the cutoff.
    assert DATES[CUTOFF_IDX + 1] in seen["in_window"]
    assert DATES[CUTOFF_IDX + 1] not in seen["post_cutoff"]
    # First post-cutoff score month's return month is post_cutoff.
    assert DATES[CUTOFF_IDX + 2] in seen["post_cutoff"]
    assert DATES[CUTOFF_IDX + 2] not in seen["in_window"]
    assert DATES[0] not in seen["in_window"]


def test_contamination_gap():
    scores, prices = _data(informative_until=CUTOFF_IDX + 1)
    assert _eval(scores, prices).contamination_gap_ic > 0.3


def test_overlap_reported():
    scores, prices = _data()
    report = _eval(scores, prices, baselines={"momentum": momentum_panel(prices)})
    assert isinstance(report.overlap["momentum"], float)


def test_trials_flow_into_deflated_sharpe():
    scores, prices = _data(noise=40.0)
    one = _eval(scores, prices, n_trials=1).windows[0].deflated_sharpe.deflated_sharpe_ratio
    many = _eval(scores, prices, n_trials=50).windows[0].deflated_sharpe.deflated_sharpe_ratio
    assert many < one


def test_mismatched_grids_propagate():
    scores, prices = _data()
    prices.period_ends = DATES[:-1]
    with pytest.raises(ValueError):
        _eval(scores, prices)
