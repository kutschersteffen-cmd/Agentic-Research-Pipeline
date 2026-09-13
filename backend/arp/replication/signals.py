from __future__ import annotations

from arp.replication.characteristics_data import CharacteristicPanel
from arp.replication.price_data import PricePanel
from arp.schemas.strategy_replication import CompositeSignalComponent, SignalType, StrategySpec


def momentum_scores(panel: PricePanel, formation_idx: int, formation_period_months: int, skip_month: bool) -> dict[str, float]:
    """Jegadeesh & Titman (1993)-style momentum score: compounded return
    over the J-month window ending at `formation_idx` (inclusive), skipping
    the most recent month first when `skip_month` (some later momentum
    papers do this to avoid 1-month reversal/microstructure effects; the
    original 1993 paper's headline strategies do not).

    A ticker missing any month in the window is excluded entirely -- never
    partially scored on fewer months than the paper's own definition.
    """
    j = formation_period_months
    end = formation_idx - (1 if skip_month else 0)
    start = end - j + 1
    if start < 0:
        return {}
    scores: dict[str, float] = {}
    for ticker, rets in panel.returns.items():
        window = rets[start : end + 1]
        if len(window) < j or any(r is None for r in window):
            continue
        cum = 1.0
        for r in window:
            cum *= 1.0 + r  # type: ignore[operator]
        scores[ticker] = cum - 1.0
    return scores


def value_scores(characteristics: CharacteristicPanel, formation_idx: int, characteristic_lag_months: int) -> dict[str, float]:
    """Book-to-market (or any other single fundamental ratio) value score:
    the characteristic's own level, lagged `characteristic_lag_months`
    behind the ranking month so the score reflects a value that was
    actually public at that time -- never the ranking month's own
    (potentially not-yet-public) figure. Higher characteristic = higher
    score, consistent with assign_portfolios' "bucket 1 = highest score"
    convention: for book-to-market this makes bucket 1 the cheap/value
    names, so long_leg_portfolio=1/short_leg_portfolio=N reproduces the
    standard long-value/short-growth construction.

    A ticker with no value at the lagged index is excluded entirely.
    """
    idx = formation_idx - characteristic_lag_months
    if idx < 0 or idx >= len(characteristics.period_ends):
        return {}
    return {t: v for t, values in characteristics.values.items() if (v := values[idx]) is not None}


def _characteristic_panel_for(name: str | None, characteristics: dict[str, CharacteristicPanel] | None) -> CharacteristicPanel:
    if not name or not characteristics or name not in characteristics:
        raise ValueError(
            f"No CharacteristicPanel supplied for characteristic_name={name!r} -- see run_backtest's "
            "`characteristics` argument (a dict keyed by characteristic_name)."
        )
    return characteristics[name]


def _percentile_ranks(scores: dict[str, float]) -> dict[str, float]:
    """Maps raw scores to [0.0, 1.0] by rank (0.0 = lowest, 1.0 = highest),
    ties broken by original order. This is what lets composite_scores
    combine signals on totally different scales (a momentum return, a
    book-to-market ratio, a bounded sentiment score) -- only relative
    ordering within each component is used, never the raw magnitude.
    """
    ordered = sorted(scores.items(), key=lambda kv: kv[1])
    n = len(ordered)
    if n <= 1:
        return {t: 0.5 for t, _ in ordered}
    return {t: i / (n - 1) for i, (t, _) in enumerate(ordered)}


def component_scores(
    component: CompositeSignalComponent,
    panel: PricePanel,
    formation_idx: int,
    characteristics: dict[str, CharacteristicPanel] | None,
) -> dict[str, float]:
    """Scores one COMPOSITE sub-signal, dispatching the same way
    compute_signal_scores does for a top-level spec -- COMPOSITE itself is
    the one SignalType a component may not be (no nesting)."""
    if component.signal_type == SignalType.MOMENTUM:
        return momentum_scores(panel, formation_idx, component.formation_period_months, component.skip_month)
    if component.signal_type in (SignalType.VALUE, SignalType.TEXT_SENTIMENT):
        char_panel = _characteristic_panel_for(component.characteristic_name, characteristics)
        return value_scores(char_panel, formation_idx, component.characteristic_lag_months)
    raise NotImplementedError(f"No composite component implementation for {component.signal_type!r}")


def composite_scores(
    spec: StrategySpec,
    panel: PricePanel,
    formation_idx: int,
    characteristics: dict[str, CharacteristicPanel] | None,
) -> dict[str, float]:
    """Combines spec.composite_components into one cross-sectional score
    via weighted rank-averaging: each component's raw scores are first
    converted to a [0,1] percentile rank (see _percentile_ranks) before
    weighting, since a momentum return, a book-to-market ratio, and a
    bounded sentiment score live on incomparable scales and only their
    relative ordering is meaningful.

    A ticker's combined score is the weighted average of the ranks it
    actually has -- a ticker missing one component (e.g. no sentiment data
    that period) still gets scored on the components it does have, using
    only the weight of those; a ticker present in none of the components is
    excluded entirely, same as every other scoring function here.
    """
    weighted_sum: dict[str, float] = {}
    weight_applied: dict[str, float] = {}
    for component in spec.composite_components:
        sub_scores = component_scores(component, panel, formation_idx, characteristics)
        if len(sub_scores) < 2:
            continue  # can't meaningfully rank fewer than 2 names
        for ticker, rank in _percentile_ranks(sub_scores).items():
            weighted_sum[ticker] = weighted_sum.get(ticker, 0.0) + rank * component.weight
            weight_applied[ticker] = weight_applied.get(ticker, 0.0) + component.weight
    return {t: weighted_sum[t] / weight_applied[t] for t in weighted_sum if weight_applied[t] > 0}


def compute_signal_scores(
    spec: StrategySpec,
    panel: PricePanel,
    formation_idx: int,
    *,
    characteristics: dict[str, CharacteristicPanel] | None = None,
) -> dict[str, float]:
    """Dispatches to the scoring function for spec.signal_type. Add a new
    branch (and a new function above) for each new strategy family this
    module supports -- see SignalType. `characteristics` is a dict keyed by
    characteristic_name, since a COMPOSITE spec's components may each need
    a different one (e.g. book_to_market for a value component, a
    sentiment score for a text-signal component) at the same formation
    date.
    """
    if spec.signal_type == SignalType.MOMENTUM:
        return momentum_scores(panel, formation_idx, spec.formation_period_months, spec.skip_month)
    if spec.signal_type in (SignalType.VALUE, SignalType.TEXT_SENTIMENT):
        char_panel = _characteristic_panel_for(spec.characteristic_name, characteristics)
        return value_scores(char_panel, formation_idx, spec.characteristic_lag_months)
    if spec.signal_type == SignalType.COMPOSITE:
        return composite_scores(spec, panel, formation_idx, characteristics)
    raise NotImplementedError(f"No signal implementation for {spec.signal_type!r}")


def assign_portfolios(scores: dict[str, float], num_portfolios: int) -> dict[str, int]:
    """Splits `scores` into `num_portfolios` contiguous buckets by rank,
    highest score first (bucket 1 = highest signal, bucket num_portfolios =
    lowest) -- the standard decile/quintile sort used by every strategy
    this module implements. Buckets are sized as evenly as possible; when
    the universe doesn't divide evenly, earlier (higher-signal) buckets
    absorb the remainder.
    """
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    n = len(ranked)
    buckets: dict[str, int] = {}
    for i, (ticker, _) in enumerate(ranked):
        bucket = min(num_portfolios, (i * num_portfolios) // n + 1)
        buckets[ticker] = bucket
    return buckets
