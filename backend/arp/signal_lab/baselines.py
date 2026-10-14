from __future__ import annotations

from arp.replication.characteristics_data import CharacteristicPanel
from arp.replication.price_data import PricePanel
from arp.replication.signals import momentum_scores


def momentum_panel(
    prices: PricePanel, *, formation_period_months: int = 12, skip_month: bool = True
) -> CharacteristicPanel:
    values: dict[str, list[float | None]] = {t: [] for t in prices.returns}
    for i in range(len(prices.period_ends)):
        scores = momentum_scores(prices, i, formation_period_months, skip_month)
        for t in values:
            values[t].append(scores.get(t))
    return CharacteristicPanel(period_ends=list(prices.period_ends), values=values, source="price_momentum")
