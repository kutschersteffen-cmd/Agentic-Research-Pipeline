from __future__ import annotations

from arp.schemas.strategy_replication import RebalanceFrequency, StrategySpec

_FIXED_INTERVAL_MONTHS = {
    RebalanceFrequency.MONTHLY: 1,
    RebalanceFrequency.QUARTERLY: 3,
    RebalanceFrequency.ANNUAL: 12,
}


def resolve_rebalance_interval_months(spec: StrategySpec) -> int:
    """How often (in months) a new portfolio is formed for `spec`.

    MONTHLY/QUARTERLY/ANNUAL imply a fixed interval of 1/3/12 months.
    CUSTOM reads `spec.rebalance_interval_months` directly -- a paper with
    an oddball schedule (every 2 months, every 18 months, ...) is a spec
    field, not a new RebalanceFrequency member.
    """
    if spec.rebalance_frequency == RebalanceFrequency.CUSTOM:
        if not spec.rebalance_interval_months or spec.rebalance_interval_months < 1:
            raise ValueError("rebalance_frequency=CUSTOM requires a positive integer rebalance_interval_months.")
        return spec.rebalance_interval_months
    return _FIXED_INTERVAL_MONTHS[spec.rebalance_frequency]


def resolve_rebalance_months(period_ends: list[str], interval_months: int, anchor_month: int | None) -> set[int]:
    """Which absolute indices into `period_ends` are valid formation
    (re-ranking) dates, for a portfolio re-formed every `interval_months`
    months.

    - **No anchor** (or a 1-month interval, where an anchor would be
      moot): every `interval_months`-th index counted from the very first
      period in the panel -- 0, interval, 2*interval, ... . Simplest
      behavior, and the only sensible one for monthly rebalancing.
    - **An anchor month** (1=Jan..12=Dec): rebalances land on the first
      period whose calendar month equals `anchor_month`, then every
      `interval_months` panel entries after that. `anchor_month=6` with
      `interval_months=12` reproduces the classic Fama & French
      June-aligned annual rebalance; `anchor_month=2` with
      `interval_months=3` rebalances every February/May/August/November.
      If the anchor month never occurs in the panel (e.g. a panel shorter
      than a year), there are no rebalance dates at all -- an empty set,
      not an error, since the caller (run_backtest) already treats "no
      formation this period" as a normal, warned-about condition.
    """
    if anchor_month is None or interval_months <= 1:
        return set(range(0, len(period_ends), interval_months))
    anchor_idx = next((i for i, d in enumerate(period_ends) if int(d[5:7]) == anchor_month), None)
    if anchor_idx is None:
        return set()
    return set(range(anchor_idx, len(period_ends), interval_months))
