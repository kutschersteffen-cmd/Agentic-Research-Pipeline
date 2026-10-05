"""The Risk Monitoring -> stewardship handoff (process gap #4).

Open portfolio alerts become company fields (`alert.*`), so the house
monitoring rules can raise a stewardship trigger from them and a person can
open an engagement from that trigger. Resolved and false-positive alerts do
not count.
"""

from __future__ import annotations

from collections import defaultdict

from arp.schemas.portfolio_monitoring import Alert, AlertCategory, AlertStatus

LIVE = {AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED, AlertStatus.ESCALATED}


def issuer_fields(alerts: list[Alert]) -> dict[str, dict]:
    fields: dict[str, dict] = defaultdict(lambda: {**{f"alert.open_{c.value}": 0 for c in AlertCategory}, "alert.open_total": 0})
    for a in alerts:
        if a.company_id and a.status in LIVE:
            fields[a.company_id][f"alert.open_{a.category.value}"] += 1
            fields[a.company_id]["alert.open_total"] += 1
    return dict(fields)
