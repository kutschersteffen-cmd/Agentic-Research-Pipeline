from __future__ import annotations

from arp.portfolio import resolution_review
from arp.schemas.portfolio import SecurityRef, SecurityResolution
from arp.storage.portfolio_store import PortfolioStore


def _seed(store: PortfolioStore, security_id: str = "s1", *, needs_review: bool = True) -> None:
    store.save_security(SecurityRef(security_id=security_id, name="Acme", asset_class="equity", currency="EUR", company_id="wrong_id"))
    store.save_resolution(
        SecurityResolution(security_id=security_id, company_id="wrong_id", confidence=0.3, method="name_fuzzy", needs_review=needs_review)
    )


def test_pending_lists_securities_below_threshold(tmp_path):
    store = PortfolioStore(tmp_path)
    _seed(store, "s1")
    _seed(store, "s2", needs_review=False)

    assert [r["security_id"] for r in resolution_review.list_pending(store)] == ["s1"]


def test_record_decision_removes_item_from_pending(tmp_path):
    store = PortfolioStore(tmp_path)
    _seed(store)

    resolution_review.record_decision(store, "s1", "accept", "jane.pm")

    assert resolution_review.list_pending(store) == []


def test_latest_decision_wins(tmp_path):
    store = PortfolioStore(tmp_path)
    _seed(store)

    resolution_review.record_decision(store, "s1", "reject", "jane.pm")
    resolution_review.record_decision(store, "s1", "accept", "sam", "second look")

    assert resolution_review.latest_decisions(store)["s1"]["decision"] == "accept"


def test_override_corrects_company_id(tmp_path):
    store = PortfolioStore(tmp_path)
    _seed(store)

    resolution_review.record_decision(store, "s1", "override", "jane.pm", override_value="acme")

    assert store.get_security("s1").company_id == "acme"
    assert resolution_review.list_pending(store) == []


def test_legacy_climate_conflict_events_are_ignored(tmp_path):
    store = PortfolioStore(tmp_path)
    _seed(store)
    store.append_governance_event(
        "decision_recorded",
        {"decision": {"item_type": "climate_conflict", "item_key": "s1", "decision": "accept", "decided_by": "x"}},
    )
    store.append_governance_event("policy_changed", {"change": {"setting_name": "x", "new_value": 1}})

    assert [r["security_id"] for r in resolution_review.list_pending(store)] == ["s1"]
    assert resolution_review.latest_decisions(store) == {}
