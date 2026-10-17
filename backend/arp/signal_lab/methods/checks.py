from __future__ import annotations

import math
from dataclasses import replace

from arp.replication.characteristics_data import CharacteristicPanel
from arp.replication.price_data import PricePanel
from arp.signal_lab.methods.base import MethodInput, run_method
from arp.signal_lab.times import month_end_time


def _same(a: float | None, b: float | None) -> bool:
    return a is None and b is None or a is not None and b is not None and math.isclose(a, b)


def lookahead_violations(spec: dict, inp: MethodInput, *, at: list[int] | None = None) -> list[tuple[str, int]]:
    """(issuer, index) wherever a value at index <= k changes when everything after grid index k is cut off."""
    ends = inp.prices.period_ends
    full = run_method(spec, inp).panel.values
    bad: list[tuple[str, int]] = []
    for k in range(2, len(ends)) if at is None else at:
        cut = month_end_time(ends[k])
        short = replace(
            inp,
            texts=[t for t in inp.texts if t.event_time <= cut],
            prices=PricePanel(ends[: k + 1], {t: r[: k + 1] for t, r in inp.prices.returns.items()}, inp.prices.source),
            panels={
                n: CharacteristicPanel(p.period_ends[: k + 1], {t: v[: k + 1] for t, v in p.values.items()}, p.source)
                for n, p in inp.panels.items()
            },
        )
        got = run_method(spec, short).panel.values
        for issuer, vals in full.items():
            trunc = got.get(issuer, [])
            bad += [
                (issuer, i) for i in range(k + 1) if not _same(vals[i] if i < len(vals) else None, trunc[i] if i < len(trunc) else None)
            ]
    return sorted(set(bad), key=lambda b: (b[1], b[0]))
