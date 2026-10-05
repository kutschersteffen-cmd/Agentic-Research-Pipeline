from __future__ import annotations

from arp.schemas.portfolio import ResolutionDecision, SecurityResolution
from arp.storage.portfolio_store import PortfolioStore


def latest_decisions(store: PortfolioStore) -> dict[str, dict]:
    """Later `decision_recorded` rows win per security_id. Legacy rows of
    other item types (e.g. climate_conflict) are ignored."""
    latest: dict[str, dict] = {}
    for row in store.list_governance_events():
        if row["event_type"] == "decision_recorded" and row["decision"].get("item_type") == "entity_resolution":
            latest[row["decision"]["item_key"]] = row["decision"]
    return latest


def list_pending(store: PortfolioStore) -> list[dict]:
    """Flagged resolutions with no decision yet. `override` clears the flag itself; accept/reject only
    leave a log row, so the decision log is what drops them from pending."""
    decided = latest_decisions(store)
    return [r.model_dump() for r in store.list_resolutions_needing_review() if r.security_id not in decided]


def record_decision(
    store: PortfolioStore, item_key: str, decision: str, decided_by: str, reason: str = "", override_value: str | None = None
) -> ResolutionDecision:
    """Logs a human decision on a flagged security. `override` also writes a manual resolution and
    repoints SecurityRef.company_id (the resolution alone is not read by aggregation).
    Raises ValueError for a blank decided_by, an override without override_value, or an unknown security."""
    if not decided_by.strip():
        raise ValueError("decided_by is required")
    if decision == "override":
        if override_value is None:
            raise ValueError("override_value is required for decision='override'")
        security = store.get_security(item_key)
        if security is None:
            raise ValueError(f"Unknown security_id: {item_key!r}")
        store.save_resolution(
            SecurityResolution(security_id=item_key, company_id=override_value, confidence=1.0, method="manual", needs_review=False)
        )
        store.save_security(security.model_copy(update={"company_id": override_value}))

    record = ResolutionDecision(item_key=item_key, decision=decision, decided_by=decided_by, reason=reason, override_value=override_value)
    store.append_governance_event("decision_recorded", {"decision": record.model_dump(mode="json")})
    return record
