from __future__ import annotations

import copy
import json

import pytest

pytest.importorskip("zen")

from fastapi import HTTPException  # noqa: E402

from arp.api.routers.stewardship import (  # noqa: E402
    OpenFromTriggerRequest,
    monitoring_triggers,
    open_engagement_from_trigger,
)
from arp.config import Settings  # noqa: E402
from arp.stewardship.monitoring import evaluate, load_graph, preview  # noqa: E402
from arp.stewardship.policies import PolicyStore  # noqa: E402
from arp.stewardship.process import SAMPLE_PATH, StreamStore  # noqa: E402
from arp.storage.engagement_store import EngagementStore  # noqa: E402

SAMPLE = json.loads(SAMPLE_PATH.read_text())


def _one(fields: dict, holding: dict | None = None) -> dict:
    return {
        "issuers": [{"issuer_id": "X", "name": "X", "region": "EU", "sector": "S", "fields": fields, "holding": holding or {}}]
    }


def test_one_issuer_can_raise_several_triggers_and_missing_data_raises_none():
    rules = {t["rule"] for t in evaluate(load_graph(), _one({"controversy.max_severity": 5}, {"change_pct": 80}), [])}
    assert rules == {"severe_controversy", "position_jump"}
    assert evaluate(load_graph(), _one({}), []) == []


def test_sample_triggers_are_valid_and_unmatched_without_engagements():
    triggers = evaluate(load_graph(), SAMPLE, [])
    assert triggers and all(t["engagement_id"] is None and t["severity"] in {"low", "medium", "high"} for t in triggers)


def test_a_trigger_is_matched_to_an_open_engagement_on_the_same_theme(tmp_path):
    store = EngagementStore(tmp_path)
    _, issue = store.open_issue("SYN10", "Synthetic Company 10", theme="climate_transition")
    store.open_issue("SYN09", "Synthetic Company 09", theme="board_governance")  # other theme: no match
    by_issuer = {t["issuer_id"]: t for t in evaluate(load_graph(), SAMPLE, store.list_all())}
    assert by_issuer["SYN10"]["engagement_id"] == issue.issue_id
    assert by_issuer["SYN09"]["engagement_id"] is None


def test_preview_shows_who_a_stricter_threshold_flags():
    candidate = copy.deepcopy(load_graph())
    table = next(n for n in candidate["nodes"] if n["id"] == "monitoring_rules")
    next(r for r in table["content"]["rules"] if r["_id"] == "clti_laggard")["clti"] = "< 80"
    result = preview(candidate, load_graph(), SAMPLE, [])
    assert result["by_rule_candidate"]["clti_laggard"] > result["by_rule_active"]["clti_laggard"]
    assert result["newly_flagged"] and not result["no_longer_flagged"]


def test_an_invalid_trigger_type_is_rejected_on_save(tmp_path):
    graph = copy.deepcopy(load_graph())
    table = next(n for n in graph["nodes"] if n["id"] == "monitoring_rules")
    table["content"]["rules"][0]["typ"] = "'gossip'"
    table["content"]["rules"][0]["clti"] = ""  # fires for every issuer
    with pytest.raises(ValueError, match="invalid trigger"):
        PolicyStore(tmp_path).save("monitoring_rules", graph, "", "Designer", SAMPLE)


def test_open_engagement_from_a_trigger_uses_the_rule_and_only_once(tmp_path):
    streams, engagements = StreamStore(tmp_path / "s"), EngagementStore(tmp_path / "e")
    body = OpenFromTriggerRequest(issuer_id="SYN10", rule="clti_laggard", decided_by="Analyst")
    opened = open_engagement_from_trigger(body, streams, engagements)
    [issue] = engagements.get("SYN10").issues
    assert (issue.theme, issue.severity.value, issue.source.value) == ("climate_transition", "high", "monitoring_rule")
    assert opened["issue_id"] == issue.issue_id
    attached = next(t for t in monitoring_triggers(Settings(), streams, engagements)["triggers"] if t["rule"] == "clti_laggard")
    assert attached["engagement_id"] == issue.issue_id
    with pytest.raises(HTTPException) as again:
        open_engagement_from_trigger(body, streams, engagements)
    assert again.value.status_code == 409
    with pytest.raises(HTTPException) as unknown:
        open_engagement_from_trigger(
            OpenFromTriggerRequest(issuer_id="SYN01", rule="clti_laggard", decided_by="A"), streams, engagements
        )
    assert unknown.value.status_code == 404
