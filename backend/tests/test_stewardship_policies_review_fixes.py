"""Tiers review fixes, PR 2 (spec tiers-review-fixes): old tier keys anywhere in a graph, loud missing versions."""

from __future__ import annotations

import copy
import json

import pytest

pytest.importorskip("zen")

from arp.stewardship import escalation  # noqa: E402
from arp.stewardship.policies import ESCALATION_RULES_FORMAT, PolicyStore  # noqa: E402
from arp.stewardship.process import SAMPLE_PATH, client_store  # noqa: E402

COVERAGE = r"^Coverage rules may only propose bilateral, letter or monitor \(found {}\)$"
ESCALATION = r"^Escalation rules may only name bilateral, letter or monitor \(found {}\)$"


@pytest.fixture
def sample():
    return json.loads(SAMPLE_PATH.read_text())


def _with_expression(graph: dict, expression: str) -> dict:
    """The coverage graph with an expression node between the table and the output that sets `tier`."""
    graph = copy.deepcopy(graph)
    node = {"id": "x", "name": "x", "type": "expressionNode", "position": {"x": 0, "y": 0}}
    node["content"] = {"expressions": [{"id": "e", "key": "tier", "value": expression}], "passThrough": True}
    graph["nodes"].append(node)
    graph["edges"] = [e for e in graph["edges"] if e["targetId"] != "output"] + [
        {"id": "t-x", "sourceId": "coverage_tiers", "targetId": "x", "type": "edge"},
        {"id": "x-o", "sourceId": "x", "targetId": "output", "type": "edge"},
    ]
    return graph


@pytest.mark.parametrize(
    ("expression", "old"),
    [
        ("'priority_bilateral'", "priority_bilateral"),  # AC-14
        ("holding.index_weight_pct > 100 ? 'systemic' : tier", "systemic"),  # AC-15: fires for no sample issuer
        ('"scaled_baseline"', "scaled_baseline"),  # double quotes
    ],
)
def test_old_tier_key_in_a_coverage_expression_is_rejected(tmp_path, sample, expression, old):
    store = PolicyStore(tmp_path)
    graph = _with_expression(store.content("coverage_rules", 0), expression)
    with pytest.raises(ValueError, match=COVERAGE.format(old)):
        store.save("coverage_rules", graph, "", "A", sample)
    assert [v["version"] for v in store.versions("coverage_rules")] == [0]  # AC-28


def test_old_tier_key_in_house_tier_caps_is_rejected(tmp_path, sample):
    # AC-16
    store = PolicyStore(tmp_path)
    graph = copy.deepcopy(store.content("escalation_rules", 0))
    caps = next(n for n in graph["nodes"] if n["id"] == "tier_caps")
    next(r for r in caps["content"]["rules"] if r["_id"] == "monitor")["t"] = "'systemic'"
    with pytest.raises(ValueError, match=ESCALATION.format("systemic")):
        store.save("escalation_rules", graph, "", "A", sample)
    assert [v["version"] for v in store.versions("escalation_rules")] == [0]


def test_old_tier_key_in_client_escalation_is_rejected(tmp_path, sample):
    # AC-17
    store = client_store(tmp_path, "client-s")
    graph = copy.deepcopy(escalation.load_client_example())
    caps = next(n for n in graph["nodes"] if n["id"] == "tier_caps")
    next(r for r in caps["content"]["rules"] if r["_id"] == "climate_to_vote")["t"] = "'scaled_baseline'"
    with pytest.raises(ValueError, match=ESCALATION.format("scaled_baseline")):
        store.save("escalation_rules", graph, "", "A", sample)
    assert [v["version"] for v in store.versions("escalation_rules")] == [0]


def test_unchanged_defaults_still_save(tmp_path, sample):
    # AC-20, and the client example
    store = PolicyStore(tmp_path)
    for policy in ("coverage_rules", "escalation_rules"):
        assert store.save(policy, store.content(policy, 0), "", "A", sample) == 1
    assert client_store(tmp_path, "client-s").save("escalation_rules", escalation.load_client_example(), "", "A", sample) == 1


def test_activation_of_a_missing_version_fails_loudly(tmp_path):
    # AC-19 (AC-18 at unit level)
    d = tmp_path / "policies" / "escalation_rules"
    d.mkdir(parents=True)
    content = PolicyStore(tmp_path).content("escalation_rules", 0)
    record = {"version": 1, "note": "", "created_by": "A", "created_at": "2026-11-01T00:00:00+00:00", "content": content}
    (d / "v1.json").write_text(json.dumps(record | {"rules_format": ESCALATION_RULES_FORMAT}))
    (d / "activations.jsonl").write_text(json.dumps({"version": 1, "approved_by": "B", "approved_at": "2026-11-02T00:00:00+00:00"}) + "\n")  # fmt: skip
    assert PolicyStore(tmp_path).active_version("escalation_rules") == 1
    (d / "v1.json").unlink()
    with pytest.raises(KeyError, match="escalation_rules v1"):
        PolicyStore(tmp_path).active_version("escalation_rules")
