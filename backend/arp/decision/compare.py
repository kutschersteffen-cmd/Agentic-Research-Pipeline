from __future__ import annotations

from arp.decision import overrides
from arp.decision.dataset import Dataset
from arp.decision.mechanism import apply_mechanism
from arp.decision.roles import pretty
from arp.schemas.decision import DecisionComparison, DecisionResult, EntityMovement, MechanismConfig

_MAX_DRIVERS = 3


def hold_cuts(config: MechanismConfig, before: DecisionResult) -> MechanismConfig:
    """The framework with the earlier snapshot's cut-points pinned, for
    scoring the later one. Quantile or natural-break cuts drawn afresh move
    with the field, so an entity whose score stood still could change tier
    with no criterion behind it. Fixed cut-points are left as they are."""
    if before.cuts_origin == "absolute":
        return config
    return config.model_copy(update={"cut_mode": "absolute", "pinned_cuts": list(before.effective_cuts)})


def compare_datasets(before: Dataset, after: Dataset, config: MechanismConfig, store) -> DecisionComparison:
    """`config` over two snapshots, each with its reviewers' overrides from
    `store` (a DecisionStore), the later one scored on the earlier one's cuts."""
    first = apply_mechanism(before, config, overrides=overrides.load(store.overrides_path(before.dataset_id)))
    return compare_results(
        first,
        apply_mechanism(after, hold_cuts(config, first), overrides=overrides.load(store.overrides_path(after.dataset_id))),
        label_before=before.as_of or before.name,
        label_after=after.as_of or after.name,
    )


def compare_results(
    before: DecisionResult,
    after: DecisionResult,
    *,
    label_before: str = "before",
    label_after: str = "after",
) -> DecisionComparison:
    """The same framework applied to two snapshots, and what moved.

    Only meaningful with the framework version pinned on both sides: a
    tier change under two different frameworks says nothing about the
    company, only about the frameworks. That is checked rather than
    assumed, and a mismatch is reported instead of quietly compared.
    """
    comparable = before.framework_id == after.framework_id and before.framework_version == after.framework_version
    reason = None
    if not comparable:
        reason = (
            f"scored under different frameworks ({before.framework_id} v{before.framework_version} vs. "
            f"{after.framework_id} v{after.framework_version}) -- any movement shown is a difference between the "
            "frameworks as much as a change in the entities"
        )

    before_by_key = {e.entity_key: e for e in before.entities}
    after_by_key = {e.entity_key: e for e in after.entities}
    movements: list[EntityMovement] = []
    improved = worsened = unchanged = 0

    for key, new in after_by_key.items():
        old = before_by_key.get(key)
        if old is None:
            continue
        tier_delta = (new.tier - old.tier) if (new.tier is not None and old.tier is not None) else None
        if tier_delta is not None:
            if tier_delta < 0:
                improved += 1
            elif tier_delta > 0:
                worsened += 1
            else:
                unchanged += 1
        movements.append(
            EntityMovement(
                entity_key=key,
                name=new.name,
                tier_before=old.tier,
                tier_after=new.tier,
                tier_delta=tier_delta,
                score_before=old.score,
                score_after=new.score,
                score_delta=(new.score - old.score) if (new.score is not None and old.score is not None) else None,
                rank_before=old.rank,
                rank_after=new.rank,
                rank_delta=(new.rank - old.rank) if (new.rank is not None and old.rank is not None) else None,
                status_before=old.status,
                status_after=new.status,
                drivers=_drivers(old, new),
            )
        )

    caveat = None
    if before.norm == "percentile" and after.norm == "percentile":
        caveat = (
            "both snapshots were scored on percentile ranks, which measure position within the field. An entity "
            "that improved in absolute terms shows no movement unless its ordering changed, and an entity that "
            "stood still can move simply because its peers did. For period-on-period comparison, score on min-max "
            "or z-score so the scale means the same thing in both snapshots."
        )

    cuts_moved = None
    if before.effective_cuts != after.effective_cuts:
        cuts_moved = (
            f"the cut-points moved from {' / '.join(f'{c:.1f}' for c in before.effective_cuts)} to "
            f"{' / '.join(f'{c:.1f}' for c in after.effective_cuts)}, so a tier can change on an unchanged score"
        )

    movements.sort(key=lambda m: (-(abs(m.score_delta) if m.score_delta is not None else -1)))
    return DecisionComparison(
        framework_id=after.framework_id,
        framework_version=after.framework_version,
        label_before=label_before,
        label_after=label_after,
        improved=improved,
        worsened=worsened,
        unchanged=unchanged,
        entered=len([k for k in after_by_key if k not in before_by_key]),
        left=len([k for k in before_by_key if k not in after_by_key]),
        movements=movements,
        comparable=comparable,
        incomparable_reason=reason,
        caveat=caveat,
        cut_points=list(after.effective_cuts),
        missing_columns=sorted(set(before.missing_columns) | set(after.missing_columns)),
        cuts_moved=cuts_moved,
    )


def _drivers(old, new) -> list[str]:
    """Which criteria actually moved the score. A tier change with no named
    driver is the shape of a data problem, not of progress, and the list
    being empty says so."""
    before_by_column = {c.column: c for c in old.contributions}
    deltas: list[tuple[float, str]] = []
    for contribution in new.contributions:
        previous = before_by_column.get(contribution.column)
        if previous is None or previous.normalised is None or contribution.normalised is None:
            continue
        delta = contribution.contribution - previous.contribution
        if abs(delta) >= 0.5:
            deltas.append((abs(delta), f"{pretty(contribution.column)} {'+' if delta > 0 else ''}{delta:.1f}"))
    deltas.sort(key=lambda d: -d[0])
    return [label for _, label in deltas[:_MAX_DRIVERS]]
