from __future__ import annotations

import copy
import json

import pytest

pytest.importorskip("zen")

from arp.stewardship.policies import PolicyStore, coverage_preview, voting_preview  # noqa: E402
from arp.stewardship.process import SAMPLE_PATH, StreamStore, flow, tier_review  # noqa: E402

pytestmark = pytest.mark.usefixtures("sample_house_universe", "pg")


@pytest.fixture
def sample():
    return json.loads(SAMPLE_PATH.read_text())


def _stricter_voting(policy: dict) -> dict:
    policy = copy.deepcopy(policy)
    for p in policy["positions"]:
        if p["issue_id"] == "board.independence":
            p["parameters"]["min_independent_pct"] = 90
    return policy


def test_version_zero_is_the_bundled_draft_and_active_by_default(tmp_path):
    store = PolicyStore(tmp_path)
    assert store.active_version("house_voting") == 0
    assert [v["version"] for v in store.versions("coverage_rules")] == [0]


def test_save_validates_and_stamps_then_activation_needs_an_approver(tmp_path, sample):
    store = PolicyStore(tmp_path)
    version = store.save("house_voting", _stricter_voting(store.active("house_voting")), "stricter", "designer", sample)
    assert version == 1 and store.content("house_voting", 1)["version"] == "v1"
    assert store.active_version("house_voting") == 0  # saving never activates
    with pytest.raises(ValueError):
        store.activate("house_voting", 1, " ")
    with pytest.raises(ValueError, match="Four-eyes"):
        store.activate("house_voting", 1, "Designer")  # the author cannot approve their own version
    store.activate("house_voting", 1, "approver")
    assert store.active_version("house_voting") == 1
    store.activate("house_voting", 0, "approver")  # roll back: the log keeps both
    assert store.active_version("house_voting") == 0 and len(store.activations("house_voting")) == 2


def test_a_torn_activation_log_fails_loudly_instead_of_falling_back(tmp_path, sample):
    store = PolicyStore(tmp_path)
    store.save("house_voting", _stricter_voting(store.active("house_voting")), "stricter", "designer", sample)
    store.activate("house_voting", 1, "approver")
    with (tmp_path / "policies" / "house_voting" / "activations.jsonl").open("a") as f:
        f.write('{"version": 0, "appro')  # a crash mid-append
    with pytest.raises(json.JSONDecodeError):
        store.active_version("house_voting")


def test_invalid_versions_are_never_stored(tmp_path, sample):
    store = PolicyStore(tmp_path)
    broken_voting = {**store.active("house_voting"), "positions": store.active("house_voting")["positions"][:-1]}
    with pytest.raises(ValueError, match="exactly one position"):
        store.save("house_voting", broken_voting, "", "designer", sample)
    broken_rules = copy.deepcopy(store.active("coverage_rules"))
    broken_rules["nodes"][1]["content"]["rules"][-1]["t"] = "'not_a_tier'"
    with pytest.raises(ValueError):
        store.save("coverage_rules", broken_rules, "", "designer", sample)
    assert [v["version"] for v in store.versions("house_voting")] == [0]


def test_voting_preview_backtests_candidate_against_active(tmp_path, sample):
    store = PolicyStore(tmp_path)
    active = store.active("house_voting")
    same = voting_preview(active, active, sample)
    assert same["changed"] == 0
    stricter = voting_preview(_stricter_voting(active), active, sample)
    assert stricter["changed"] > 0 and set(stricter["affected_by_issue"]) == {"board.independence"}


def test_coverage_preview_lists_the_companies_that_would_move(tmp_path, sample):
    store = PolicyStore(tmp_path)
    active = store.active("coverage_rules")
    assert coverage_preview(active, active, sample, [])["changes"] == []
    everyone_priority = copy.deepcopy(active)
    for row in everyone_priority["nodes"][1]["content"]["rules"]:
        row["t"] = "'bilateral'"
    preview = coverage_preview(everyone_priority, active, sample, [])
    assert preview["distribution_candidate"] == {"Bilateral": preview["companies"]}
    assert len(preview["changes"]) == preview["companies"] - preview["distribution_active"].get("Bilateral", 0)


def test_flow_and_tier_review_use_the_active_versions(tmp_path, sample):
    streams = StreamStore(tmp_path)
    store = PolicyStore(tmp_path)

    def expected_against() -> str:
        stage = next(s for s in flow("house", streams, [], 45)["stages"] if s["id"] == "voting")
        return next(m["value"] for m in stage["metrics"] if m["label"] == "Expected against")

    before = expected_against()
    store.activate(
        "house_voting", store.save("house_voting", _stricter_voting(store.active("house_voting")), "", "d", sample), "a"
    )
    assert expected_against() != before

    rules = copy.deepcopy(store.active("coverage_rules"))
    for row in rules["nodes"][1]["content"]["rules"]:
        row["t"] = "'monitor'"
    store.activate("coverage_rules", store.save("coverage_rules", rules, "", "d", sample), "a")
    assert {c["tier"] for c in tier_review(tmp_path, sample, [])["changes"]} == {"monitor"}


@pytest.mark.parametrize(("rule_id", "old"), [("default", "scaled_baseline"), ("small_position", "systemic")])
def test_new_coverage_versions_may_not_propose_an_old_tier(tmp_path, sample, rule_id, old):
    # AC-9, AC-18: read from the table, so a row that never fires on the sample is caught too
    graph = copy.deepcopy(PolicyStore(tmp_path).active("coverage_rules"))
    table = next(n for n in graph["nodes"] if n["id"] == "coverage_tiers")
    next(r for r in table["content"]["rules"] if r["_id"] == rule_id)["t"] = f"'{old}'"
    with pytest.raises(ValueError, match=rf"^Coverage rules may only propose bilateral, letter or monitor \(found {old}\)$"):
        PolicyStore(tmp_path).save("coverage_rules", graph, "", "designer", sample)
    assert [v["version"] for v in PolicyStore(tmp_path).versions("coverage_rules")] == [0]


def _main_format_escalation_v1(root) -> None:
    """An escalation_rules v1, saved and activated the way main wrote it before the three tiers."""
    d = root / "policies" / "escalation_rules"
    d.mkdir(parents=True)
    content = PolicyStore(root).content("escalation_rules", 0)
    (d / "v1.json").write_text(json.dumps({"version": 1, "note": "", "created_by": "A", "created_at": "2026-11-01T00:00:00+00:00", "content": content}))  # fmt: skip
    (d / "activations.jsonl").write_text(json.dumps({"version": 1, "approved_by": "B", "approved_at": "2026-11-02T00:00:00+00:00"}) + "\n")  # fmt: skip


def test_escalation_versions_written_for_the_old_tiers_are_retired(tmp_path, sample):
    # AC-24, AC-25, AC-27 (house and client store alike)
    from arp.stewardship.process import client_store

    for store in (PolicyStore(tmp_path), client_store(tmp_path, "client-s")):
        _main_format_escalation_v1(store.root.parent)
        assert store.active_version("escalation_rules") == 0
        assert [v["version"] for v in store.versions("escalation_rules")] == [0, 1]
        with pytest.raises(ValueError, match=r"^Version 1 was written for the old tiers or ladder; save a new version$"):
            store.activate("escalation_rules", 1, "C")
        version = store.save("escalation_rules", store.content("escalation_rules", 0), "", "A", sample)
        store.activate("escalation_rules", version, "B")
        assert store.active_version("escalation_rules") == version
