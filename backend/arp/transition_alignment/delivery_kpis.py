"""Sector delivery KPIs: the latest counted actual of each KPI against its range (spec 2026-10-21 delivery KPIs §3).
Pure: no DB, no model."""

from __future__ import annotations

import math

from arp.schemas.transition_alignment import ActionOut, KpiOut
from arp.transition_alignment.benchmarks import SectorEntry, kpi_prefixes, range_text
from arp.transition_alignment.capex import Fact

NO_KPI = "No delivery KPI for this sector."


def _number(v) -> float | None:
    """A fact value as a number ("14" included); None when it isn't one. Never raises."""
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(str(v).replace(",", ""))
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def score_delivery_kpis(sector: SectorEntry, isic: str, facts: list[Fact],
                        actions: list[ActionOut]) -> tuple[list[KpiOut], str | None]:
    """The sector's KPIs whose ISIC prefixes match `isic`, in file order, plus the note when none matches."""
    out = []
    for k in sector.delivery_kpis:
        if not any(isic.startswith(p) for p in kpi_prefixes(sector, k)):
            continue
        # the latest period_end wins; ties go to the lowest fact id
        f = min((f for f in facts if f.field_id == k.field), default=None, key=lambda f: (-(f.year or 0), f.fact_id))
        value = _number(f.value) if f else None
        position = None if value is None else round(min(max(value, 0) / k.points[-1].value, 1) * 100, 1)
        out.append(KpiOut(
            id=k.id, label=k.label, field_id=k.field, cite=k.cite, value=value, year=f.year if f else None,
            fact_ids=[f.fact_id] if f else [], range_text=range_text(k.points), position_pct=position,
            action_keys=[a.key for a in actions if a.action_id in k.levers],
        ))
    return out, None if out else NO_KPI
