from __future__ import annotations

import pytest

from arp.config import Settings
from arp.portfolio import governance
from arp.portfolio.datapoint_mapping import resolve_field_value
from arp.schemas.portfolio import DataPointObservation, SecurityRef, SecurityResolution
from arp.storage.portfolio_store import PortfolioStore


def _seed_flagged_resolution(store: PortfolioStore, *, company_id: str = "wrong_id") -> None:
    store.save_security(SecurityRef(security_id="s1", name="Acme", asset_class="equity", currency="EUR", company_id=company_id))
    store.save_resolution(SecurityResolution(security_id="s1", company_id=company_id, confidence=0.3, method="name_fuzzy", needs_review=True))


def _seed_flagged_conflict(store: PortfolioStore, *, value: float = 500.0) -> None:
    store.append_observation(
        DataPointObservation(
            company_id="c1", field_id="climate_carbon_intensity", field_name="Carbon Intensity",
            value=value, source="internal_api", conflicting_sources=True, conflicting_value=300.0,
        )
    )


# --- accept/reject never mutate the underlying flag ---


def test_accept_decision_does_not_mutate_flag_but_leaves_pending(tmp_path):
    store = PortfolioStore(tmp_path)
    _seed_flagged_resolution(store)

    governance.record_decision(store, "entity_resolution", "s1", "accept", "jane.pm")

    assert len(store.list_resolutions_needing_review()) == 1  # raw flag untouched
    assert governance.list_pending_reviews(store)["entity_resolution"] == []  # but no longer pending


def test_reject_decision_climate_conflict_stays_flagged_but_not_pending(tmp_path):
    store = PortfolioStore(tmp_path)
    _seed_flagged_conflict(store)

    governance.record_decision(store, "climate_conflict", "c1:climate_carbon_intensity", "reject", "jane.pm")

    from arp.portfolio.datapoint_mapping import list_conflicting_observations

    assert len(list_conflicting_observations(store)) == 1
    assert governance.list_pending_reviews(store)["climate_conflict"] == []


# --- override has real computational effect ---


def test_override_entity_resolution_clears_flag_and_updates_security(tmp_path):
    store = PortfolioStore(tmp_path)
    _seed_flagged_resolution(store)

    governance.record_decision(store, "entity_resolution", "s1", "override", "jane.pm", override_value="correct_id")

    assert store.get_security("s1").company_id == "correct_id"
    resolution = store.get_resolution("s1")
    assert resolution.method == "manual"
    assert resolution.needs_review is False
    assert store.list_resolutions_needing_review() == []  # cleared entirely, not just filtered from pending


def test_override_climate_conflict_writes_new_observation_and_clears_conflict(tmp_path):
    store = PortfolioStore(tmp_path)
    _seed_flagged_conflict(store)

    governance.record_decision(store, "climate_conflict", "c1:climate_carbon_intensity", "override", "jane.pm", override_value=310.0)

    resolved = resolve_field_value(store, "c1", "climate_carbon_intensity")
    assert resolved.value == 310.0
    assert resolved.conflicting_sources is False
    from arp.portfolio.datapoint_mapping import list_conflicting_observations

    assert list_conflicting_observations(store) == []
    # append-only: the original flagged observation is still in history
    assert len(store.load_observations("c1", "climate_carbon_intensity")) == 2


# --- validation ---


def test_record_decision_requires_decided_by(tmp_path):
    store = PortfolioStore(tmp_path)
    _seed_flagged_resolution(store)
    with pytest.raises(ValueError, match="decided_by"):
        governance.record_decision(store, "entity_resolution", "s1", "accept", "")


def test_record_decision_override_requires_override_value(tmp_path):
    store = PortfolioStore(tmp_path)
    _seed_flagged_resolution(store)
    with pytest.raises(ValueError, match="override_value"):
        governance.record_decision(store, "entity_resolution", "s1", "override", "jane.pm")


# --- fold ---


def test_latest_decision_wins_per_item_key(tmp_path):
    store = PortfolioStore(tmp_path)
    _seed_flagged_resolution(store)

    governance.record_decision(store, "entity_resolution", "s1", "accept", "jane.pm")
    governance.record_decision(store, "entity_resolution", "s1", "override", "jane.pm", override_value="correct_id")

    latest = governance.latest_decisions(store)
    assert latest["s1"]["decision"] == "override"
    assert len(governance.decision_history(store, "s1")) == 2


# --- policy ---


def test_get_current_policy_defaults_to_settings_when_no_history(tmp_path):
    store = PortfolioStore(tmp_path)
    settings = Settings()
    policy = governance.get_current_policy(store, settings)
    assert policy["portfolio_confidence_review_threshold"] == settings.portfolio_confidence_review_threshold
    assert policy["climate_validation_tolerance_pct"] == settings.climate_validation_tolerance_pct
    assert governance.policy_history(store) == []


def test_set_policy_updates_current_value_and_appends_history_oldest_first(tmp_path):
    store = PortfolioStore(tmp_path)
    settings = Settings()

    governance.set_policy(store, settings, "climate_validation_tolerance_pct", 0.10, "jane.pm", "tightening")
    governance.set_policy(store, settings, "climate_validation_tolerance_pct", 0.05, "jane.pm", "tightening further")

    assert governance.get_current_policy(store, settings)["climate_validation_tolerance_pct"] == 0.05
    history = governance.policy_history(store)
    assert [h["new_value"] for h in history] == [0.10, 0.05]
    assert history[1]["old_value"] == 0.10


def test_set_policy_requires_changed_by(tmp_path):
    store = PortfolioStore(tmp_path)
    settings = Settings()
    with pytest.raises(ValueError, match="changed_by"):
        governance.set_policy(store, settings, "climate_validation_tolerance_pct", 0.10, "")


# --- owners ---


def test_list_owners_empty_until_assigned(tmp_path):
    store = PortfolioStore(tmp_path)
    assert governance.list_owners(store) == {}


def test_set_owner_latest_wins_per_category(tmp_path):
    store = PortfolioStore(tmp_path)
    governance.set_owner(store, "climate_conflict", "sam.analyst", "jane.pm")
    governance.set_owner(store, "climate_conflict", "alex.analyst", "jane.pm")

    owners = governance.list_owners(store)
    assert owners["climate_conflict"].owner == "alex.analyst"


def test_set_owner_requires_assigned_by(tmp_path):
    store = PortfolioStore(tmp_path)
    with pytest.raises(ValueError, match="assigned_by"):
        governance.set_owner(store, "climate_conflict", "sam.analyst", "")
