"""Score lineage AC-13 and AC-21: published rows keep reasons and value ids; company fields carry status."""

from __future__ import annotations

from arp.decision.mechanism import apply_mechanism
from arp.decision.publish import as_fields, publish
from tests.test_score_lineage_engine import da, s_config


def _snapshot():
    config = s_config(ratified=True)
    dataset = da()
    return publish(dataset, config, apply_mechanism(dataset, config, with_stability=False), published_by="Bob",
                   id_column="company_id")


def _row(snapshot, entity_id):
    return next(r for r in snapshot.rows if r.entity_id == entity_id)


def test_ac_13_published_rows_keep_reasons_ids_and_source():
    snap = _snapshot()
    c = _row(snap, "C")
    assert (c.status, c.reasons) == ("no_score", ["required_missing: auth_scope1 (not_in_dataset)"])
    assert [(k.column, k.value_id) for k in _row(snap, "A").criteria] == [("auth_scope1", 11), ("auth_capex", 21)]
    assert snap.source == "authoritative"


def test_ac_21_company_fields():
    fields = as_fields(_snapshot())
    p = "decision.fw_s"
    assert fields["C"] == {f"{p}.status": "no_score", f"{p}.reasons": "required_missing: auth_scope1 (not_in_dataset)"}
    assert set(fields["A"]) == {f"{p}.{k}" for k in ("score", "tier", "tier_name", "rank", "rank_max", "status", "reasons")}
    assert (fields["A"][f"{p}.status"], fields["A"][f"{p}.reasons"]) == ("scored", "")
