"""Publishing a decision result: the handoff from Decision Studio to the
functions that act on it (stewardship coverage tiers, index construction).

Only a ratified framework version can be published, and the snapshot is
frozen: a consumer reads exactly what a named person published, never a
re-score. Entities are matched to issuers by an id column, not by name.
"""

from __future__ import annotations

from arp.decision.dataset import Dataset
from arp.schemas.decision import DecisionResult, MechanismConfig, PublishedDecision, PublishedRow

ID_COLUMNS = ("company_id", "issuer_id", "entity_id", "id")


def find_id_column(dataset: Dataset) -> str | None:
    by_lower = {c.lower(): c for c in dataset.columns}
    return next((by_lower[c] for c in ID_COLUMNS if c in by_lower), None)


def hold_published_cuts(config: MechanismConfig, snapshots: list[PublishedDecision]) -> tuple[MechanismConfig, str | None]:
    """The framework with its first publication's cut-points pinned, and
    that snapshot's id. Quantile or natural-break cuts drawn afresh move with
    the field, so a later table would re-tier entities whose scores stood
    still. Fixed cut-points, or a version never published, are left alone."""
    if config.cut_mode == "absolute":
        return config, None
    earlier = [
        s for s in snapshots if s.framework_id == config.framework_id and s.framework_version == config.version and s.cut_points
    ]
    if not earlier:
        return config, None
    first = min(earlier, key=lambda s: s.published_at)
    return config.model_copy(update={"cut_mode": "absolute", "pinned_cuts": list(first.cut_points)}), first.snapshot_id


def publish(
    dataset: Dataset,
    config: MechanismConfig,
    result: DecisionResult,
    *,
    published_by: str,
    id_column: str | None = None,
    note: str = "",
    cuts_held_from: str | None = None,
) -> PublishedDecision:
    if not config.ratified:
        raise ValueError(f"{config.name} v{config.version} is not ratified; only a ratified framework can be published.")
    if result.missing_columns:
        raise ValueError(
            f"Not published: the table lacks columns the framework uses ({', '.join(result.missing_columns)}); "
            "a gate on one cannot fire and a criterion drops out."
        )
    if not published_by.strip():
        raise ValueError("Publishing needs published_by.")
    column = id_column or find_id_column(dataset)
    if column is None or column not in dataset.columns:
        raise ValueError(f"No id column to match entities to issuers (looked for {', '.join(ID_COLUMNS)}); name one explicitly.")
    # apply_mechanism emits one entity per dataset row, in row order.
    if len(result.entities) != len(dataset.rows):
        raise ValueError("The result does not line up with the dataset rows.")
    rows = [
        PublishedRow(
            entity_id=str(row.get(column) or "").strip(),
            name=e.name,
            score=e.score,
            tier=e.tier,
            tier_name=e.tier_name,
            rank=e.rank,
            rank_min=e.rank_min,
            rank_max=e.rank_max,
            status=e.status,
        )
        for row, e in zip(dataset.rows, result.entities, strict=True)
        if str(row.get(column) or "").strip()
    ]
    return PublishedDecision(
        framework_id=config.framework_id,
        framework_version=config.version,
        framework_name=config.name,
        dataset_id=dataset.dataset_id,
        dataset_name=dataset.name,
        as_of=dataset.as_of,
        id_column=column,
        published_by=published_by.strip(),
        note=note,
        cut_points=list(result.effective_cuts),
        cuts_held_from=cuts_held_from,
        rows=rows,
    )


def field_prefix(snapshot: PublishedDecision) -> str:
    return f"decision.{snapshot.framework_id}"


def as_fields(snapshot: PublishedDecision) -> dict[str, dict[str, float | int | str | None]]:
    """entity id -> flat company fields, the form every consumer reads."""
    p = field_prefix(snapshot)
    return {
        r.entity_id: {
            f"{p}.score": r.score,
            f"{p}.tier": r.tier,
            f"{p}.tier_name": r.tier_name,
            f"{p}.rank": r.rank,
            f"{p}.rank_max": r.rank_max,
        }
        for r in snapshot.rows
    }
