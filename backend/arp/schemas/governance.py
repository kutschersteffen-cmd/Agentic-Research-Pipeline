from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from arp.schemas.common import now_iso

GovernanceItemType = Literal["entity_resolution", "climate_conflict"]
GovernanceDecisionType = Literal["accept", "override", "reject"]
PolicySettingName = Literal["portfolio_confidence_review_threshold", "climate_validation_tolerance_pct"]


class GovernanceDecision(BaseModel):
    """A human decision on a flagged item -- `item_key` is a security_id
    for entity_resolution, or "{company_id}:{field_id}" for
    climate_conflict. `accept`/`reject` are pure audit annotations (the
    underlying flag is never mutated); `override` has real effect -- see
    arp/portfolio/governance.py::record_decision for what it actually
    writes. `decided_by` is required, mirroring
    arp.schemas.engagement.EscalationTransition/
    arp.schemas.portfolio_monitoring.AlertTransition's human checkpoint.
    """

    item_type: GovernanceItemType
    item_key: str
    decision: GovernanceDecisionType
    decided_by: str
    reason: str = ""
    override_value: float | str | bool | None = None
    decided_at: str = Field(default_factory=now_iso)


class RiskCategoryOwner(BaseModel):
    """category is a free string, not an enum -- entity_resolution/
    climate_conflict here, plus threshold_breach/news_controversy from §3
    already exist as plausible categories, and more will appear as other
    spec sections get built."""

    category: str
    owner: str
    assigned_by: str
    assigned_at: str = Field(default_factory=now_iso)


class PolicyChange(BaseModel):
    """One entry in a governance setting's change history. The *current*
    value of a setting is derived by folding these (latest per
    setting_name wins), never stored as a separate mutable snapshot -- see
    arp/portfolio/governance.py::get_current_policy."""

    setting_name: PolicySettingName
    old_value: float
    new_value: float
    changed_by: str
    reason: str = ""
    changed_at: str = Field(default_factory=now_iso)
