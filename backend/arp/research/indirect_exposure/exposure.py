from __future__ import annotations

from arp.research.indirect_exposure.leontief import LeontiefModel
from arp.schemas.exposure import IndirectExposureResult


def compute_indirect_exposure(
    company_id: str,
    isic_code: str,
    model: LeontiefModel,
    core_codes: set[str],
    icio_edition: str,
) -> IndirectExposureResult | None:
    """Computes structural exposure via Leontief propagation. Pure
    arithmetic on an already-built model -- no LLM call, effectively free
    per company. Returns None if the company's industry or none of the
    theme's core industries are present in this model.
    """
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

    return IndirectExposureResult(
        company_id=company_id,
        isic_code=isic_code,
        isic_label=model.labels.get(isic_code),
        upstream_exposure=min(max(upstream, 0.0), 1.0),
        downstream_exposure=min(max(downstream, 0.0), 1.0),
        core_sector=isic_code in core_codes,
        icio_edition=icio_edition,
    )
