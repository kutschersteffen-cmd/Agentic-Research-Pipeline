from __future__ import annotations

import math
from itertools import combinations

from arp.replication.backtest_engine import run_backtest
from arp.replication.characteristics_data import CharacteristicPanel
from arp.replication.price_data import PricePanel
from arp.schemas.cpcv import PBOReport
from arp.schemas.strategy_replication import StrategySpec

_NEGATIVE_INFINITY = float("-inf")


def _make_blocks(period_ends: list[str], num_blocks: int) -> list[list[str]]:
    """Splits `period_ends` (assumed already sorted, chronological) into
    `num_blocks` contiguous, roughly-equal-sized blocks by observation
    count -- the "S groups" of Bailey et al.'s CSCV procedure."""
    if num_blocks < 2 or num_blocks % 2 != 0:
        raise ValueError(f"num_blocks must be even and >= 2 (CSCV splits into two equal halves per split), got {num_blocks}.")
    n = len(period_ends)
    if n < num_blocks:
        raise ValueError(f"Only {n} periods available in [period_start, period_end] -- cannot split into {num_blocks} blocks.")
    base, remainder = divmod(n, num_blocks)
    blocks: list[list[str]] = []
    start = 0
    for i in range(num_blocks):
        size = base + (1 if i < remainder else 0)
        blocks.append(period_ends[start : start + size])
        start += size
    return blocks


def _purged_embargoed_train_period_ends(
    blocks: list[list[str]], test_block_indices: set[int], purge_months: int, embargo_months: int
) -> set[str]:
    """All periods belonging to non-test blocks, minus a buffer around each
    test block's boundaries: `purge_months` periods immediately BEFORE a
    test block (whose holding/formation window could otherwise overlap
    into the test block -- Lopez de Prado's "purging") and
    `embargo_months` periods immediately AFTER it (guarding against
    serial-correlation leakage from the test block bleeding into
    subsequent training -- "embargo"). This is a practical, period-count
    approximation of purging/embargo (as popularized in Lopez de Prado's
    "Advances in Financial Machine Learning"), not an exact per-signal
    overlap computation against every candidate's own lookback window.
    """
    all_period_ends = [d for block in blocks for d in block]
    idx_of = {d: i for i, d in enumerate(all_period_ends)}
    test_dates = {d for i in test_block_indices for d in blocks[i]}

    purge_idxs: set[int] = set()
    for i in sorted(test_block_indices):
        block = blocks[i]
        if not block:
            continue
        start_idx, end_idx = idx_of[block[0]], idx_of[block[-1]]
        purge_idxs.update(range(max(0, start_idx - purge_months), start_idx))
        purge_idxs.update(range(end_idx + 1, min(len(all_period_ends), end_idx + 1 + embargo_months)))
    purge_dates = {all_period_ends[j] for j in purge_idxs}

    return {d for d in all_period_ends if d not in test_dates and d not in purge_dates}


def run_pbo_analysis(
    candidates: list[StrategySpec],
    panel: PricePanel,
    *,
    period_start: str,
    period_end: str,
    num_blocks: int = 8,
    purge_months: int | None = None,
    embargo_months: int = 1,
    characteristics: dict[str, CharacteristicPanel] | None = None,
) -> PBOReport:
    """Estimates the Probability of Backtest Overfitting across
    `candidates` (2+ StrategySpec variants -- e.g. different formation
    windows, characteristics, or universes considered for the same paper)
    via Combinatorially Symmetric Cross-Validation, per Bailey, Borwein,
    Lopez de Prado & Zhu, "The Probability of Backtest Overfitting".

    Reuses `run_backtest`'s `allowed_period_ends` hook (see
    backtest_engine.py) to evaluate every purged/embargoed train/test
    split against the SAME already-fetched panel, rather than re-slicing
    or re-fetching data per split -- each of the `num_blocks` blocks
    covers a contiguous stretch of `panel`'s period_ends within
    [period_start, period_end]; every way of choosing half the blocks as
    the test set (num_blocks choose num_blocks/2) is one split.

    `purge_months` defaults to the largest holding_period_months across
    `candidates` (a spec's return realization can lag its formation date
    by up to that many months, so training periods within that many
    months of a test block could otherwise leak test-adjacent information
    into the training-side ranking) -- pass an explicit value to override.
    """
    if len(candidates) < 2:
        raise ValueError("run_pbo_analysis needs at least 2 candidate specs to compare -- PBO is undefined for a single strategy.")
    spec_ids = [c.spec_id for c in candidates]
    if len(set(spec_ids)) != len(spec_ids):
        raise ValueError("candidates must have distinct spec_id values.")

    period_ends_in_window = [d for d in panel.period_ends if period_start <= d <= period_end]
    blocks = _make_blocks(period_ends_in_window, num_blocks)

    if purge_months is None:
        purge_months = max((c.holding_period_months for c in candidates), default=0)

    logits: list[float] = []
    selection_count: dict[str, int] = {spec_id: 0 for spec_id in spec_ids}

    for test_block_indices in combinations(range(num_blocks), num_blocks // 2):
        test_indices_set = set(test_block_indices)
        test_dates = {d for i in test_indices_set for d in blocks[i]}
        train_dates = _purged_embargoed_train_period_ends(blocks, test_indices_set, purge_months, embargo_months)
        if not train_dates or not test_dates:
            continue

        train_sharpes: dict[str, float] = {}
        test_sharpes: dict[str, float] = {}
        for spec in candidates:
            train_result = run_backtest(
                spec, panel, period_label="cpcv_train", period_start=period_start, period_end=period_end,
                characteristics=characteristics, allowed_period_ends=train_dates,
            )
            test_result = run_backtest(
                spec, panel, period_label="cpcv_test", period_start=period_start, period_end=period_end,
                characteristics=characteristics, allowed_period_ends=test_dates,
            )
            train_sharpes[spec.spec_id] = train_result.long_short.sharpe_ratio if train_result.long_short.sharpe_ratio is not None else _NEGATIVE_INFINITY
            test_sharpes[spec.spec_id] = test_result.long_short.sharpe_ratio if test_result.long_short.sharpe_ratio is not None else _NEGATIVE_INFINITY

        best_in_sample_id = max(train_sharpes, key=lambda spec_id: train_sharpes[spec_id])
        selection_count[best_in_sample_id] += 1

        ranked_by_test = sorted(spec_ids, key=lambda spec_id: test_sharpes[spec_id])  # ascending: rank 1 = worst OOS
        rank_of_best = ranked_by_test.index(best_in_sample_id) + 1  # 1..N
        n = len(spec_ids)
        omega = rank_of_best / (n + 1)
        omega = min(max(omega, 1e-9), 1 - 1e-9)
        logits.append(math.log(omega / (1 - omega)))

    if not logits:
        raise ValueError(
            f"No split produced any train/test periods -- num_blocks={num_blocks} with purge_months={purge_months}, "
            f"embargo_months={embargo_months} left nothing after purging on a panel of {len(period_ends_in_window)} periods. "
            "Reduce num_blocks/purge_months/embargo_months or widen the sample window."
        )

    pbo = sum(1 for lam in logits if lam <= 0) / len(logits)
    notes = (
        f"{len(logits)} split(s) evaluated across {len(candidates)} candidates. PBO={pbo:.2f}: "
        + ("more likely than not that the in-sample-best candidate was a lucky pick, not a robust finding."
           if pbo > 0.5 else "the in-sample-best candidate held up out-of-sample more often than not, but this is a screen, not proof of skill.")
    )

    return PBOReport(
        candidate_spec_ids=spec_ids,
        num_blocks=num_blocks,
        num_splits=len(logits),
        purge_months=purge_months,
        embargo_months=embargo_months,
        logits=logits,
        probability_of_backtest_overfitting=pbo,
        per_candidate_selection_count=selection_count,
        notes=notes,
    )
