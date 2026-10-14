from __future__ import annotations

import numpy as np

from arp.replication.price_data import PricePanel
from arp.replication.signals import momentum_scores
from arp.signal_lab.baselines import momentum_panel


def test_momentum_panel_matches_signals():
    rng = np.random.default_rng(0)
    dates = [f"2020-{m:02d}-28" for m in range(1, 13)] + [f"2021-{m:02d}-28" for m in range(1, 13)]
    returns = {f"T{k}": [None] + list(rng.normal(0.01, 0.05, 23)) for k in range(5)}
    returns["T0"][15] = None
    panel = PricePanel(period_ends=dates, returns=returns, source="test")

    out = momentum_panel(panel)

    assert out.source == "price_momentum"
    assert out.period_ends == dates
    defined = 0
    for i in range(len(dates)):
        expected = momentum_scores(panel, i, 12, True)
        for t in returns:
            if t in expected:
                assert out.values[t][i] == expected[t]
                defined += 1
            else:
                assert out.values[t][i] is None
    assert defined > 0
