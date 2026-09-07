from __future__ import annotations

from arp.config import Settings
from arp.portfolio import datapoint_mapping
from arp.schemas.governance import GovernanceDecision, PolicyChange, RiskCategoryOwner
from arp.schemas.portfolio import DataPointObservation, SecurityResolution
from arp.storage.portfolio_store import PortfolioStore

_POLICY_DEFAULTS = {
    "portfolio_confidence_review_threshold": lambda settings: settings.portfolio_confidence_review_threshold,
    "climate_validation_tolerance_pct": lambda settings: settings.climate_validation_tolerance_pct,
}


def _climate_conflict_key(company_id: str, field_id: str) -> str:
    return f"{company_id}:{field_id}"


def latest_decisions(store: PortfolioStore) -> dict[str, dict]:
    """Later `decision_recorded` rows win per item_key -- same "later JSONL
    rows win" fold as orchestration.review_queue.latest_decisions, applied
    to this module's unified governance event log instead of a per-run
    review-decisions file."""
    latest: dict[str, dict] = {}
    for row in store.list_governance_events():
        if row["event_type"] == "decision_recorded":
            latest[row["decision"]["item_key"]] = row["decision"]
    return latest


def decision_history(store: PortfolioStore, item_key: str) -> list[dict]:
    """Every decision ever recorded for item_key, oldest first."""
    return [row["decision"] for row in store.list_governance_events() if row["event_type"] == "decision_recorded" and row["decision"]["item_key"] == item_key]


def list_pending_reviews(store: PortfolioStore) -> dict[str, list]:
    """The raw flagged lists (list_resolutions_needing_review /
    list_conflicting_observations) keep returning every currently-flagged
    item unconditionally -- unchanged, still the source of truth for "is
    this flagged." This filters that down to what's actually still
    awaiting a decision, by cross-referencing the folded decision log.
    An `override` decision doesn't need filtering here since it clears the
    underlying flag itself (see record_decision) -- it simply won't be in
    the raw list any more by the time this runs. `accept`/`reject` never
    touch the flag, so they rely entirely on this filter to disappear from
    "pending".
    """
    decided = latest_decisions(store)
    pending_resolutions = [r for r in store.list_resolutions_needing_review() if r.security_id not in decided]
    pending_conflicts = [
        o for o in datapoint_mapping.list_conflicting_observations(store) if _climate_conflict_key(o.company_id, o.field_id) not in decided
    ]
    return {"entity_resolution": pending_resolutions, "climate_conflict": pending_conflicts}


def record_decision(
    store: PortfolioStore,
    item_type: str,
    item_key: str,
    decision: str,
    decided_by: str,
    reason: str = "",
    override_value: float | str | bool | None = None,
) -> GovernanceDecision:
    """Records a human decision on a flagged item. `accept`/`reject` are
    pure audit annotations -- nothing about the underlying flag changes,
    only the decision log grows (see list_pending_reviews for how that's
    enough to drop it from "pending"). `override` has real computational
    effect:

    - entity_resolution: writes a fresh SecurityResolution
      (method="manual", confidence=1.0, needs_review=False) *and* updates
      the SecurityRef.company_id via save_security -- the resolution alone
      has no effect on aggregation, since mock_data.py sets
      SecurityRef.company_id directly and nothing reads a resolution's
      company_id back into it. Without the save_security call this would
      be a no-op review record, not a real correction.
    - climate_conflict: appends a *new* DataPointObservation
      (source="internal_api", conflicting_sources=False, the flagged value
      replaced) rather than mutating history -- because it's internal_api
      and more recent, datapoint_mapping.resolve_field_value's existing
      source-priority cascade naturally picks it up going forward.

    Raises ValueError if decided_by is blank, or decision="override" with
    no override_value.
    """
    if not decided_by.strip():
        raise ValueError("decided_by is required")
    if decision == "override" and override_value is None:
        raise ValueError("override_value is required for decision='override'")

    if decision == "override" and item_type == "entity_resolution":
        security = store.get_security(item_key)
        if security is None:
            raise ValueError(f"Unknown security_id: {item_key!r}")
        store.save_resolution(
            SecurityResolution(security_id=item_key, company_id=str(override_value), confidence=1.0, method="manual", needs_review=False)
        )
        store.save_security(security.model_copy(update={"company_id": str(override_value)}))
    elif decision == "override" and item_type == "climate_conflict":
        company_id, field_id = item_key.split(":", 1)
        prior = store.load_observations(company_id, field_id)
        if not prior:
            raise ValueError(f"No observations for {item_key!r}")
        latest = prior[-1]
        store.append_observation(
            DataPointObservation(
                company_id=company_id, field_id=field_id, field_name=latest.field_name, value=override_value,
                unit=latest.unit, period=latest.period, source="internal_api", conflicting_sources=False,
                notes=f"Governance override by {decided_by}: {reason}" if reason else f"Governance override by {decided_by}",
            )
        )

    record = GovernanceDecision(
        item_type=item_type, item_key=item_key, decision=decision, decided_by=decided_by, reason=reason, override_value=override_value
    )
    store.append_governance_event("decision_recorded", {"decision": record.model_dump(mode="json")})
    return record


def get_current_policy(store: PortfolioStore, settings: Settings) -> dict[str, float]:
    """Folds `policy_changed` events (latest row per setting_name wins),
    falling back to the Settings env default for any setting with no
    history yet -- no separate mutable snapshot file, so there's only one
    source of truth for "what changed and what is it now"."""
    values = {name: default(settings) for name, default in _POLICY_DEFAULTS.items()}
    for row in store.list_governance_events():
        if row["event_type"] == "policy_changed":
            change = row["change"]
            values[change["setting_name"]] = change["new_value"]
    return values


def policy_history(store: PortfolioStore) -> list[dict]:
    """Every policy_changed row, oldest first -- the history itself, not
    folded."""
    return [row["change"] for row in store.list_governance_events() if row["event_type"] == "policy_changed"]


def set_policy(store: PortfolioStore, settings: Settings, setting_name: str, new_value: float, changed_by: str, reason: str = "") -> PolicyChange:
    if not changed_by.strip():
        raise ValueError("changed_by is required")
    old_value = get_current_policy(store, settings)[setting_name]
    change = PolicyChange(setting_name=setting_name, old_value=old_value, new_value=new_value, changed_by=changed_by, reason=reason)
    store.append_governance_event("policy_changed", {"change": change.model_dump(mode="json")})
    return change


def list_owners(store: PortfolioStore) -> dict[str, RiskCategoryOwner]:
    """Folds owner_assigned events, latest per category. A category with
    no assignment simply isn't in the dict -- "unassigned" is a valid
    state, not a default owner string."""
    owners: dict[str, RiskCategoryOwner] = {}
    for row in store.list_governance_events():
        if row["event_type"] == "owner_assigned":
            owner = RiskCategoryOwner.model_validate(row["owner"])
            owners[owner.category] = owner
    return owners


def set_owner(store: PortfolioStore, category: str, owner: str, assigned_by: str) -> RiskCategoryOwner:
    if not assigned_by.strip():
        raise ValueError("assigned_by is required")
    record = RiskCategoryOwner(category=category, owner=owner, assigned_by=assigned_by)
    store.append_governance_event("owner_assigned", {"owner": record.model_dump(mode="json")})
    return record
