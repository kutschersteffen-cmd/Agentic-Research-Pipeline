from __future__ import annotations

import numpy as np

from arp.research.indirect_exposure.criticality import critical_isic_codes
from arp.research.indirect_exposure.io_import import FD_GROUPS, country_regions, group_order, region_groups
from arp.research.indirect_exposure.leontief import LeontiefModel
from arp.schemas.exposure import IndirectExposureResult, RegionalExposure


def _clamp(v: float) -> float:
    return min(max(float(v), 0.0), 1.0)


def _share(part: float, total: float) -> float:
    return float(part / total) if total > 0 else 0.0


def _demand(model: LeontiefModel, row: np.ndarray, core: np.ndarray) -> tuple[dict[str, float] | None, float | None]:
    """end_market and theme_demand_share; both None without final demand or
    when the company's final-demand-driven output is 0."""
    if model.final_demand is None:
        return None, None
    driven = row @ model.final_demand
    total = driven.sum()
    if total == 0:
        return None, None
    theme = (row[core] * model.final_demand[core].sum(axis=1)).sum() / total
    return {g: float(v / total) for g, v in zip(FD_GROUPS, driven, strict=True)}, _clamp(theme)


def _regional(model: LeontiefModel, region: str, core: np.ndarray, column: np.ndarray, row: np.ndarray) -> RegionalExposure:
    groups = np.array([region_groups()[r] for r in model.regions[core]])
    present = {region_groups()[r] for r in model.regions}

    def shares(vector: np.ndarray) -> tuple[float, dict[str, float]]:
        total = vector.sum()
        by_group = {g: _share(vector[core[groups == g]].sum(), total) for g in group_order() if g in present}
        return _clamp(sum(by_group.values())), by_group

    upstream, upstream_by_region = shares(column)
    downstream, downstream_by_region = shares(row)
    return RegionalExposure(
        region=region_groups()[region], upstream=upstream, downstream=downstream,
        upstream_by_region=upstream_by_region, downstream_by_region=downstream_by_region,
    )


def compute_indirect_exposure(
    company_id: str,
    isic_code: str,
    model: LeontiefModel,
    core_codes: set[str],
    icio_edition: str,
    *,
    critical_codes: set[str] | None = None,
    country: str | None = None,
) -> IndirectExposureResult | None:
    """Computes structural exposure via Leontief propagation. Pure
    arithmetic on an already-built model -- no LLM call, effectively free
    per company. Returns None if the company's code is unknown or covers no
    node, or the theme's core codes cover none.

    The company is the output-weighted set of nodes its code covers in the
    EXIOBASE region of its `country` (ISO alpha-2/3), or in every region
    when the country is unknown or its region not in the build; the core is
    every node a core code covers, in every region.

    `critical_codes` defaults to the bundled criticality registry's ISIC
    set (arp.research.indirect_exposure.criticality) when not supplied --
    the parameter exists so callers/tests can inject a synthetic set
    without depending on the real bundled registry's contents.
    """
    resolved_critical_codes = critical_codes if critical_codes is not None else critical_isic_codes()
    nodes = model.code_nodes.get(isic_code)
    if nodes is None:
        return None
    region = country_regions().get((country or "").upper())
    if region not in set(model.regions):
        region = None
    if region is not None:
        nodes = nodes[model.regions[nodes] == region]
    core = np.unique(np.concatenate([model.code_nodes.get(c, np.array([], dtype=np.intp)) for c in core_codes] or [[]])).astype(np.intp)
    if not len(nodes) or not len(core):
        return None

    weights = model.output[nodes] / model.output[nodes].sum()
    leontief_inverse = model.leontief_inverse
    # Upstream: of everything the company's nodes require (direct + indirect),
    # what share traces back to the theme's core nodes as suppliers.
    column = leontief_inverse[:, nodes] @ weights
    # Downstream: of everything they propagate outward (direct + indirect),
    # what share lands specifically in the theme's core nodes.
    row = weights @ leontief_inverse[nodes, :]

    end_market, theme_demand_share = _demand(model, row, core)
    ghg = model.ghg_t_per_meur
    return IndirectExposureResult(
        company_id=company_id,
        isic_code=isic_code,
        isic_label=model.labels.get(isic_code),
        upstream_exposure=_clamp(_share(column[core].sum(), column.sum())),
        downstream_exposure=_clamp(_share(row[core].sum(), row.sum())),
        core_sector=isic_code in core_codes,
        critical_input=isic_code in resolved_critical_codes,
        icio_edition=icio_edition,
        end_market=end_market,
        theme_demand_share=theme_demand_share,
        ghg_direct_t_per_meur=float(weights @ ghg[nodes]),
        ghg_supply_chain_t_per_meur=float(ghg @ column),
        regional=_regional(model, region, core, column, row) if region is not None else None,
    )
