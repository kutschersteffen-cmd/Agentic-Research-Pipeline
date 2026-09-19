from __future__ import annotations

import pytest

from arp.decision.dataset import build_dataset
from arp.decision.diffing import describe_changes
from arp.schemas.decision import AuditEntry, Criterion, Dimension, GateRule, MechanismConfig
from arp.storage.decision_store import DecisionStore


def _config(**kwargs) -> MechanismConfig:
    base = MechanismConfig(
        framework_id="fw_test",
        name="Climate engagement",
        dimensions=[Dimension(id="d0", name="Disclosure", weight=1.0)],
        criteria=[Criterion(column="Emissions_Data_Coverage_pct", dimension_id="d0", direction="higher")],
    )
    return base.model_copy(update=kwargs)


def test_versions_are_never_edited_in_place(tmp_path):
    """A ratified framework is the justification attached to a decision
    about a company. A justification that can be rewritten afterwards is
    not one."""
    store = DecisionStore(tmp_path)
    store.save(_config())
    store.ratify("fw_test")
    with pytest.raises(ValueError, match="ratified"):
        store.save(_config(version=1, name="quietly different"))


def test_new_version_leaves_the_previous_one_readable(tmp_path):
    store = DecisionStore(tmp_path)
    store.save(_config())
    store.ratify("fw_test")
    store.new_version(_config(name="v2 name", min_coverage_pct=80))

    assert store.get("fw_test").version == 2
    assert store.get("fw_test", 1).name == "Climate engagement"
    assert store.get("fw_test", 1).ratified is True
    assert store.get("fw_test", 2).ratified is False, "a new version starts unratified"
    assert store.list_versions("fw_test") == [1, 2]


def test_audit_travels_with_the_version_it_describes(tmp_path):
    store = DecisionStore(tmp_path)
    audit = [AuditEntry(stage="Roles", item="x", decision="criterion", why="numeric with spread")]
    store.save(_config(), audit)
    assert [e.decision for e in store.get_audit("fw_test", 1)] == ["criterion"]
    assert store.get_audit("fw_test", 2) == []


def test_datasets_round_trip_with_their_confidence(tmp_path):
    store = DecisionStore(tmp_path)
    dataset = build_dataset("t.csv", [["Name", "Value"], ["A", "1"], ["B", "2"]])
    dataset.confidence["Value"] = [0.9, None]
    store.save_dataset(dataset)
    loaded = store.get_dataset(dataset.dataset_id)
    assert loaded.rows == dataset.rows
    assert loaded.confidence["Value"] == [0.9, None]


def test_unknown_framework_returns_none_rather_than_raising(tmp_path):
    assert DecisionStore(tmp_path).get("fw_missing") is None


# --- the human half of the audit log ------------------------------------


def test_direction_override_is_recorded_as_a_human_decision():
    """The whole point of the log is telling apart what the data proposed
    from what a person then changed."""
    before = _config()
    after = _config(criteria=[Criterion(column="Emissions_Data_Coverage_pct", dimension_id="d0", direction="lower")])
    entries = describe_changes(before, after, by="analyst@example.com")
    assert len(entries) == 1
    assert entries[0].origin == "human"
    assert entries[0].by == "analyst@example.com"
    assert "direction higher -> lower" in entries[0].decision
    assert "inverts a ranking" in entries[0].why


def test_setting_weight_and_gate_edits_are_all_captured():
    before = _config()
    after = _config(
        min_coverage_pct=75,
        weighting="equal",
        normalise_within="Sector",
        gates=[GateRule(column="Coal_Expansion_Flag", outcome="exclude")],
        dimensions=[Dimension(id="d0", name="Disclosure", weight=3.0)],
    )
    decisions = " | ".join(e.decision for e in describe_changes(before, after))
    assert "60 -> 75" in decisions
    assert "balanced -> equal" in decisions
    assert "(none) -> Sector" in decisions
    assert "gate added" in decisions
    assert "weight 1 -> 3" in decisions
    assert all(e.origin == "human" for e in describe_changes(before, after))


def test_an_unchanged_framework_produces_no_edit_entries():
    assert describe_changes(_config(), _config()) == []
