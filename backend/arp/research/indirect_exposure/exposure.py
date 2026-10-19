from __future__ import annotations

import numpy as np

from arp.research.indirect_exposure.criticality import critical_isic_codes
from arp.research.indirect_exposure.io_import import FD_GROUPS, company_region_group
from arp.research.indirect_exposure.leontief import LeontiefModel
from arp.schemas.exposure import IndirectExposureResult, RegionalExposure


def _clamp(v: float) -> float:
    return min(max(float(v), 0.0), 1.0)


def _demand(model: LeontiefModel, idx: int, core_indices: list[int]) -> tuple[dict[str, float] | None, float | None]:
    """end_market and theme_demand_share (spec call 13); both None without
    final demand or when the industry's final-demand-driven output is 0."""
    if model.final_demand is None:
        return None, None
    driven = model.leontief_inverse[idx] @ model.final_demand  # (L·y_c)[idx] per group
    total = driven.sum()
    if total == 0:
        return None, None
    y = model.final_demand.sum(axis=1)
    theme = sum(model.leontief_inverse[idx, k] * y[k] for k in core_indices) / total
    return {g: float(v / total) for g, v in zip(FD_GROUPS, driven, strict=True)}, _clamp(theme)


def _ghg(model: LeontiefModel, idx: int) -> tuple[float | None, float | None]:
    """Direct and supply-chain t CO2e per million EUR (spec call 14)."""
    if model.ghg_kg is None or model.total_output is None:
        return None, None
    x = model.total_output
    direct = np.divide(model.ghg_kg / 1000, x, out=np.zeros_like(x), where=x != 0)
    return float(direct[idx]), float(direct @ model.leontief_inverse[:, idx])


def _regional(model: LeontiefModel, isic_code: str, core_codes: set[str], country: str | None) -> RegionalExposure | None:
    regional = model.regional
    group = company_region_group(country)
    if regional is None or group not in regional.groups:
        return None
    idx = regional.index.get((group, isic_code))
    if idx is None:
        return None
    inverse = regional.leontief_inverse
    core = {g: [i for c in core_codes if (i := regional.index.get((g, c))) is not None] for g in regional.groups}

    def shares(vector: np.ndarray) -> tuple[float, dict[str, float]]:
        total = vector.sum()
        by_region = {g: float(vector[ix].sum() / total) if total > 0 else 0.0 for g, ix in core.items()}
        return _clamp(sum(by_region.values())), by_region

    upstream, upstream_by_region = shares(inverse[:, idx])
    downstream, downstream_by_region = shares(inverse[idx, :])
    return RegionalExposure(
        region=group, upstream=upstream, downstream=downstream,
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
    per company. Returns None if the company's industry or none of the
    theme's core industries are present in this model.

    `critical_codes` defaults to the bundled criticality registry's ISIC
    set (arp.research.indirect_exposure.criticality) when not supplied --
    the parameter exists so callers/tests can inject a synthetic set
    without depending on the real bundled registry's contents.

    `country` (ISO alpha-2/3) picks the region group for `regional`; the
    other new fields come from the model's optional extras and stay None
    without them.
    """
    resolved_critical_codes = critical_codes if critical_codes is not None else critical_isic_codes()
    idx = model.index_of(isic_code)
    if idx is None:
        return None
    core_indices = [i for i in (model.index_of(c) for c in core_codes) if i is not None]
    if not core_indices:
        return None

    leontief_inverse = model.leontief_inverse

    # Upstream: of everything industry `idx` requires (direct + indirect),
    # what share traces back to the theme's core industries as suppliers.
    column = leontief_inverse[:, idx]
    column_total = column.sum()
    upstream = (sum(column[i] for i in core_indices) / column_total) if column_total > 0 else 0.0

    # Downstream: of everything industry `idx` propagates outward (direct +
    # indirect), what share lands specifically in the theme's core industries.
    row = leontief_inverse[idx, :]
    row_total = row.sum()
    downstream = (sum(row[j] for j in core_indices) / row_total) if row_total > 0 else 0.0

    end_market, theme_demand_share = _demand(model, idx, core_indices)
    ghg_direct, ghg_supply_chain = _ghg(model, idx)
    return IndirectExposureResult(
        company_id=company_id,
        isic_code=isic_code,
        isic_label=model.labels.get(isic_code),
        upstream_exposure=min(max(upstream, 0.0), 1.0),
        downstream_exposure=min(max(downstream, 0.0), 1.0),
        core_sector=isic_code in core_codes,
        critical_input=isic_code in resolved_critical_codes,
        icio_edition=icio_edition,
        end_market=end_market,
        theme_demand_share=theme_demand_share,
        ghg_direct_t_per_meur=ghg_direct,
        ghg_supply_chain_t_per_meur=ghg_supply_chain,
        regional=_regional(model, isic_code, core_codes, country),
    )
