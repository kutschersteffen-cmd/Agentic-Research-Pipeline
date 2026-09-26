from __future__ import annotations

import copy

from arp.decision.dataset import Dataset
from arp.decision.mechanism import apply_mechanism
from arp.decision.rules import apply_rules
from arp.schemas.decision import EntitySensitivity, MechanismConfig, TippingPoint

_DEFAULT_STEPS = 13
_MAX_MULTIPLIER = 4.0


def _dimension_shares(config: MechanismConfig) -> dict[str, float]:
    total = sum(max(0.0, d.weight) for d in config.dimensions)
    if total <= 0:
        return {d.id: 0.0 for d in config.dimensions}
    return {d.id: max(0.0, d.weight) / total * 100.0 for d in config.dimensions}


def tipping_points(
    dataset: Dataset,
    config: MechanismConfig,
    *,
    entity_keys: list[str] | None = None,
    steps: int = _DEFAULT_STEPS,
) -> list[EntitySensitivity]:
    """How far each dimension's weight must move before an entity changes
    tier.

    This is the answer to the only question a committee reliably asks of a
    ranking: how much does this depend on the weights you happened to
    choose? A tier that survives any weight in the searched range is
    reported as robust; one that flips after a two-point change is
    reported as exactly that.

    Cost is (dimensions x steps) applications of the mechanism, so the
    stability band is switched off for the intermediate runs and `steps`
    is deliberately modest. It is an on-demand analysis, not part of
    scoring.
    """
    # Rules do not depend on weights: evaluate them once, not once per step.
    if config.rule_graph:
        dataset, _ = apply_rules(dataset, config.rule_graph)
        config = config.model_copy(update={"rule_graph": None})
    baseline = apply_mechanism(dataset, config, with_stability=False)
    wanted = set(entity_keys) if entity_keys else None
    targets = [e for e in baseline.entities if e.status == "scored" and (wanted is None or e.entity_key in wanted)]
    if not targets or not config.dimensions:
        return []

    baseline_shares = _dimension_shares(config)
    # dimension id -> list of (weight share %, {entity_key: tier})
    sweeps: dict[str, list[tuple[float, dict[str, int | None]]]] = {}
    for dimension in config.dimensions:
        observations: list[tuple[float, dict[str, int | None]]] = []
        for step in range(steps):
            multiplier = _MAX_MULTIPLIER * step / (steps - 1)
            variant = copy.deepcopy(config)
            for candidate in variant.dimensions:
                if candidate.id == dimension.id:
                    candidate.weight = max(0.0, dimension.weight) * multiplier
            if sum(max(0.0, d.weight) for d in variant.dimensions) <= 0:
                continue
            result = apply_mechanism(dataset, variant, with_stability=False)
            share = _dimension_shares(variant)[dimension.id]
            observations.append((share, {e.entity_key: e.tier for e in result.entities}))
        sweeps[dimension.id] = observations

    out: list[EntitySensitivity] = []
    for entity in targets:
        points: list[TippingPoint] = []
        for dimension in config.dimensions:
            current = baseline_shares[dimension.id]
            flips = [
                (share, tiers.get(entity.entity_key))
                for share, tiers in sweeps.get(dimension.id, [])
                if tiers.get(entity.entity_key) != entity.tier
            ]
            if not flips:
                points.append(
                    TippingPoint(
                        dimension_id=dimension.id,
                        dimension_name=dimension.name,
                        current_weight_pct=round(current, 1),
                        robust=True,
                    )
                )
                continue
            share, new_tier = min(flips, key=lambda f: abs(f[0] - current))
            points.append(
                TippingPoint(
                    dimension_id=dimension.id,
                    dimension_name=dimension.name,
                    current_weight_pct=round(current, 1),
                    flip_weight_pct=round(share, 1),
                    delta_pct=round(share - current, 1),
                    new_tier=new_tier,
                    robust=False,
                )
            )
        deltas = [abs(p.delta_pct) for p in points if p.delta_pct is not None]
        out.append(
            EntitySensitivity(
                entity_key=entity.entity_key,
                name=entity.name,
                tier=entity.tier,
                score=entity.score,
                tipping_points=points,
                min_delta_pct=round(min(deltas), 1) if deltas else None,
            )
        )
    return out
