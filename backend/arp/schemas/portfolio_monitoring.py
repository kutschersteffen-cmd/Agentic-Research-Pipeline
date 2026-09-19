from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from arp.schemas.common import new_id, now_iso

RuleType = Literal["field_threshold", "concentration_threshold", "portfolio_aggregate_threshold"]
Comparator = Literal["gt", "gte", "lt", "lte"]


class AlertStatus(StrEnum):
    """A short ladder, not engagement's 7-stage one -- portfolio-risk
    alerts don't have the same multi-month lifecycle. Raising an alert
    (OPEN) is system-generated; every transition past it requires a human
    (see AlertTransition.decided_by)."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    FALSE_POSITIVE = "false_positive"


class BreachType(StrEnum):
    """Not a binary "trade-caused" -- this system has no transaction
    blotter, so a holdings-snapshot change could be a trade, a price mark,
    or an FX move. Only `portfolio_aggregate_threshold` alerts run a real
    comparison (see monitoring/evaluator.py::_classify_aggregate_drift);
    `field_threshold` is always DATA_CAUSED and `concentration_threshold`
    is always HOLDINGS_CAUSED by construction."""

    HOLDINGS_CAUSED = "holdings_caused"
    DATA_CAUSED = "data_caused"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class AlertCategory(StrEnum):
    THRESHOLD_BREACH = "threshold_breach"
    NEWS_CONTROVERSY = "news_controversy"


class AlertRule(BaseModel):
    """A configurable limit the monitoring evaluator checks on every pass.
    `field_id` is required for field_threshold/portfolio_aggregate_threshold
    (a climate field_id, e.g. climate_carbon_intensity) and ignored for
    concentration_threshold. `company_ids`/`portfolio_ids` scope which
    companies/portfolios the rule applies to; empty means "every company
    with holdings" / "every portfolio" respectively.
    """

    rule_id: str = Field(default_factory=lambda: new_id("rule"))
    name: str
    rule_type: RuleType
    field_id: str | None = None
    company_ids: list[str] = Field(default_factory=list)
    portfolio_ids: list[str] = Field(default_factory=list)
    comparator: Comparator
    threshold_value: float
    severity: Literal["low", "medium", "high"] = "medium"
    enabled: bool = True
    created_at: str = Field(default_factory=now_iso)


class AlertTransition(BaseModel):
    """Mirrors arp.schemas.engagement.EscalationTransition exactly --
    `decided_by` is required, non-optional, the human checkpoint the spec
    calls for on every escalation/resolution."""

    status: AlertStatus
    changed_at: str = Field(default_factory=now_iso)
    decided_by: str
    reason: str = ""
    owner: str | None = None


class Alert(BaseModel):
    """One raised breach or news-controversy trigger. `snapshot_date` and
    `data_point_values` are the audit inputs `_classify_aggregate_drift`
    compares a new portfolio_aggregate_threshold breach against -- kept on
    the record itself (small: one float per company in-scope), same
    philosophy as DataPointObservation keeping `conflicting_value` alongside
    `value` rather than just a flag.
    """

    alert_id: str = Field(default_factory=lambda: new_id("alrt"))
    rule_id: str | None = None
    category: AlertCategory
    scope_id: str = Field(description='company_id for company-scoped rules, or "portfolio__<portfolio_id>" for portfolio-scoped ones.')
    company_id: str | None = None
    portfolio_id: str | None = None
    triggered_at: str = Field(default_factory=now_iso)
    observed_value: float | None = None
    threshold_value: float | None = None
    breach_type: BreachType = BreachType.UNKNOWN
    snapshot_date: str | None = None
    data_point_values: dict[str, float] | None = None
    source_flag_id: str | None = None
    rationale: str = ""
    status: AlertStatus = Field(
        default=AlertStatus.OPEN,
        description="As raised, always OPEN -- the current value seen by a reader is folded from the scope's "
        "event log (the latest AlertTransition.status, if any) by monitoring/evaluator.py::list_alerts, never "
        "mutated in place on the original alert_raised event.",
    )
    owner: str | None = None


class PortfolioMonitoringScheduleConfig(BaseModel):
    """Persisted to <portfolio_monitoring_state_dir>/schedule.json -- same
    shape/role as arp.schemas.calibration.CalibrationScheduleConfig."""

    enabled: bool = False
    interval_hours: float = 6.0
    news_min_severity: Literal["low", "medium", "high"] = "medium"
    last_run_at: str | None = None
