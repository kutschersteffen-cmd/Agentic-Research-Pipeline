from __future__ import annotations

from arp.schemas.strategy_replication import (
    BacktestResult,
    ReplicationComparisonReport,
    ReplicationVerdict,
    ReportedPerformance,
)

# Reasonable, documented starting points -- not empirically tuned against a
# labeled set of replication outcomes (same caveat this codebase already
# states for its other threshold constants, e.g. Settings.arbitration_*).
MIN_SIGNIFICANT_T_STAT = 2.0
MIN_PERIODS_FOR_A_VERDICT = 12
FULL_REPLICATION_MAGNITUDE_RATIO = 0.5


def _gap_pp(measured: float | None, reference: float | None) -> float | None:
    if measured is None or reference is None:
        return None
    return measured - reference


def build_comparison_report(
    in_sample: BacktestResult,
    reported_performance: ReportedPerformance,
    *,
    out_of_sample: BacktestResult | None = None,
) -> ReplicationComparisonReport:
    """Compares an in-sample replication against the paper's own reported
    long-short performance, then (if supplied) checks whether the effect
    persists out-of-sample. See ReplicationVerdict for what each outcome
    means; the thresholds above are simple and disclosed, not a black box.
    """
    ls = in_sample.long_short
    reported_ls = reported_performance.long_short

    in_sample_gap = _gap_pp(ls.annualized_return_pct, reported_ls.annualized_return_pct)
    notes: list[str] = []

    if len(in_sample.periods) < MIN_PERIODS_FOR_A_VERDICT:
        verdict = ReplicationVerdict.INSUFFICIENT_DATA
        notes.append(
            f"Only {len(in_sample.periods)} in-sample monthly observation(s); need at least "
            f"{MIN_PERIODS_FOR_A_VERDICT} for any verdict."
        )
    elif ls.t_stat is None or abs(ls.t_stat) < MIN_SIGNIFICANT_T_STAT or (ls.annualized_return_pct or 0) <= 0:
        verdict = ReplicationVerdict.NOT_REPLICATED
        notes.append(
            f"In-sample long-short return is not statistically distinguishable from zero "
            f"(t-stat={ls.t_stat!r}) and/or non-positive."
        )
    elif reported_ls.annualized_return_pct is None:
        verdict = ReplicationVerdict.REPLICATED
        notes.append(
            "Paper's reported long-short annualized return is not available in this spec, so magnitude "
            "could not be compared -- verdict is based on in-sample significance alone."
        )
    elif reported_ls.annualized_return_pct <= 0:
        verdict = ReplicationVerdict.NOT_REPLICATED
        notes.append("Paper's own reported long-short return is non-positive; nothing to replicate.")
    elif in_sample_gap is not None and in_sample_gap >= -((1 - FULL_REPLICATION_MAGNITUDE_RATIO) * reported_ls.annualized_return_pct):
        verdict = ReplicationVerdict.REPLICATED
        notes.append(
            f"In-sample annualized long-short return ({ls.annualized_return_pct:.2f}%) is within "
            f"{int(FULL_REPLICATION_MAGNITUDE_RATIO * 100)}% of the paper's reported "
            f"{reported_ls.annualized_return_pct:.2f}%."
        )
    else:
        verdict = ReplicationVerdict.PARTIALLY_REPLICATED
        notes.append(
            f"Same sign as the paper but a material magnitude gap: replicated "
            f"{ls.annualized_return_pct:.2f}% vs. reported {reported_ls.annualized_return_pct:.2f}%."
        )

    out_of_sample_gap: float | None = None
    if out_of_sample is not None and verdict in (ReplicationVerdict.REPLICATED, ReplicationVerdict.PARTIALLY_REPLICATED):
        oos = out_of_sample.long_short
        out_of_sample_gap = _gap_pp(oos.annualized_return_pct, ls.annualized_return_pct)
        if len(out_of_sample.periods) < MIN_PERIODS_FOR_A_VERDICT:
            notes.append(
                f"Out-of-sample window has only {len(out_of_sample.periods)} observation(s); decay read is unreliable."
            )
        elif oos.t_stat is None or abs(oos.t_stat) < MIN_SIGNIFICANT_T_STAT or (oos.annualized_return_pct or 0) <= 0:
            verdict = ReplicationVerdict.DECAYED_OUT_OF_SAMPLE
            notes.append(
                f"Out-of-sample long-short return is not significant and/or non-positive "
                f"(t-stat={oos.t_stat!r}, annualized={oos.annualized_return_pct!r}%) -- the effect did not persist."
            )
        elif out_of_sample_gap is not None and out_of_sample_gap < -((1 - FULL_REPLICATION_MAGNITUDE_RATIO) * ls.annualized_return_pct):
            verdict = ReplicationVerdict.DECAYED_OUT_OF_SAMPLE
            notes.append(
                f"Out-of-sample annualized return ({oos.annualized_return_pct:.2f}%) is a material downgrade from "
                f"the in-sample replication ({ls.annualized_return_pct:.2f}%)."
            )
        else:
            notes.append(
                f"Out-of-sample annualized return ({oos.annualized_return_pct:.2f}%) is broadly consistent with "
                f"the in-sample replication -- the effect appears to persist."
            )

    return ReplicationComparisonReport(
        spec_id=in_sample.spec_id,
        in_sample=in_sample,
        out_of_sample=out_of_sample,
        reported_performance=reported_performance,
        in_sample_return_gap_pp=in_sample_gap,
        out_of_sample_return_gap_pp=out_of_sample_gap,
        verdict=verdict,
        verdict_notes=" ".join(notes),
    )
