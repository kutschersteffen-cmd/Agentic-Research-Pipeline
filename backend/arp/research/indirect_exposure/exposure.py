from __future__ import annotations

import numpy as np

from arp.research.indirect_exposure.criticality import critical_sectors as registry_critical_sectors
from arp.research.indirect_exposure.io_import import FD_GROUPS, country_regions, group_order, region_groups
from arp.research.indirect_exposure.leontief import LeontiefModel
from arp.research.indirect_exposure.nace import code_set_sectors, isic_to_nace2, nace_title
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
    sector: str,
    model: LeontiefModel,
    core_sectors: set[str],
    io_edition: str,
    *,
    critical_sectors: set[str] | None = None,
    country: str | None = None,
    nace: tuple[str, str, str] | None = None,
) -> IndirectExposureResult | None:
    """Computes structural exposure via Leontief propagation. Pure
    arithmetic on an already-built model -- no LLM call, effectively free
    per company. Returns None if the company's sector is unknown or has no
    node, or the theme's core sectors have none.

    The company is the output-weighted set of its sector's nodes in the
    EXIOBASE region of its `country` (ISO alpha-2/3), or in every region
    when the country is unknown or its region not in the build; the core is
    every node of a core sector, in every region.

    `critical_sectors` defaults to the bundled criticality registry's
    sectors (arp.research.indirect_exposure.criticality) when not supplied --
    the parameter exists so callers/tests can inject a synthetic set
    without depending on the real bundled registry's contents.

    `nace` (scheme, code, rev from value_chain.links.company_nace) replaces
    `sector`: the company is then the nodes of its NACE set.
    """
    critical = critical_sectors if critical_sectors is not None else registry_critical_sectors()
    if nace is None:
        nodes = model.code_nodes.get(sector)
        if nodes is None:
            return None
        scheme, code, label, names = "exiobase", sector, sector, {sector}
    else:
        scheme, code, rev = nace
        targets = isic_to_nace2(code) if scheme == "isic4" and len(code) == 4 else [code]
        names = code_set_sectors(*nace)
        nodes = np.flatnonzero(np.isin(model.sectors, list(names)))
        label = nace_title(targets[0], rev) if targets else None
    core_sector, critical_input = bool(names & core_sectors), bool(names & critical)
    region = country_regions().get((country or "").upper())
    if region not in set(model.regions):
        region = None
    if region is not None:
        nodes = nodes[model.regions[nodes] == region]
    core = np.unique(np.concatenate([model.code_nodes.get(c, np.array([], dtype=np.intp)) for c in core_sectors] or [[]])).astype(np.intp)
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
        isic_code=code,
        isic_label=label,
        code_scheme=scheme,
        upstream_exposure=_clamp(_share(column[core].sum(), column.sum())),
        downstream_exposure=_clamp(_share(row[core].sum(), row.sum())),
        core_sector=core_sector,
        critical_input=critical_input,
        io_edition=io_edition,
        end_market=end_market,
        theme_demand_share=theme_demand_share,
        ghg_direct_t_per_meur=float(weights @ ghg[nodes]),
        ghg_supply_chain_t_per_meur=float(ghg @ column),
        regional=_regional(model, region, core, column, row) if region is not None else None,
    )
