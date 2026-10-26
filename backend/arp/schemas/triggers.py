"""One trigger shape for risk alerts and stewardship monitoring."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from arp.schemas.portfolio_monitoring import Alert, AlertCategory

THEMES = {AlertCategory.THRESHOLD_BREACH: "climate_data", AlertCategory.NEWS_CONTROVERSY: "controversy"}


class UnifiedTrigger(BaseModel):
    trigger_id: str
    source: Literal["risk_alert", "stewardship"]
    issuer_id: str
    type: str
    theme: str
    severity: Literal["low", "medium", "high"]
    reason: str
    status: Literal["open", "acknowledged", "resolved"] = "open"
    first_seen_month: str = ""
    is_new: bool = False
    rule: str = ""  # the monitoring rule that raised it; open-engagement needs (issuer_id, rule)


def from_alert(alert: Alert) -> UnifiedTrigger:
    return UnifiedTrigger(
        trigger_id=alert.alert_id,
        source="risk_alert",
        issuer_id=alert.company_id or alert.scope_id,
        type=alert.category.value,
        theme=THEMES[alert.category],
        severity="medium",  # ponytail: alerts carry no severity; derive one when rules gain it
        reason=alert.rationale,
        status="open",
        first_seen_month=alert.triggered_at[:7],
    )
