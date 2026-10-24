from __future__ import annotations

import pytest

from arp.api.auth import Principal
from arp.ask import newest_transition_plan
from arp.decision.sources import from_transition_plan_run
from arp.orchestration.review_queue import append_decision
from arp.schemas.common import JobStatus, RunManifest
from arp.schemas.review import ReviewDecision
from tests.test_decision_sources import preset_record, store_preset_run

ALICE = Principal(user_id="u_alice", name="Alice", role="analyst")
BOB = Principal(user_id="u_bob", name="Bob", role="analyst")


def old_run(rs, run_id: str, created: str, names: list[str], *, status=JobStatus.COMPLETED, params=None) -> str:
    """A stored `transition_plan` run with one result row per company name."""
    rs.save_manifest(RunManifest(run_id=run_id, run_type="transition_plan", status=status, created_at=created, params=params or {}))
    for i, name in enumerate(names):
        rs.append_result(run_id, {
            "company_id": name.lower().replace(" ", "_"), "name": name, "disclosed_count": 10 + i, "walk_disclosed_count": 4,
            "walk_total_count": 8, "talk_disclosed_count": 6, "overall_confidence": 0.75, "needs_review": False, "by_category": [],
        })
    return run_id


def preset_run(rs, created: str, company_ids: list[str], *, status=JobStatus.COMPLETED, params=None) -> str:
    """A transition plan preset extraction run; a record's Company is its company_id upper-cased."""
    run_id = store_preset_run(rs, None, [preset_record(c) for c in company_ids])
    m = rs.load_manifest(run_id)
    rs.save_manifest(m.model_copy(update={"status": status, "created_at": created, "params": {**m.params, **(params or {})}}))
    return run_id


def ask(rs, company, who=ALICE):
    return newest_transition_plan(rs, who, company)


@pytest.fixture
def three_runs(run_store):
    """AC-3: two completed runs with BASF SE, and a newer one still running."""
    rs = run_store
    old = old_run(rs, "tp_0901", "2026-09-01T09:00:00+00:00", ["BASF SE"])
    new = preset_run(rs, "2026-10-20T09:00:00+00:00", ["basf se"])
    preset_run(rs, "2026-10-23T09:00:00+00:00", ["basf se"], status=JobStatus.RUNNING)
    return rs, old, new


def test_newest_completed_run_wins_and_running_is_skipped(three_runs):  # AC-3
    rs, _, new = three_runs
    card, _ = ask(rs, "BASF")
    assert card.run_id == new and card.run_type == "extraction"
    assert card.run_date == rs.load_manifest(new).created_at
    assert card.company == "BASF SE"


def test_figures_come_from_the_run_row(three_runs):  # AC-4
    rs, _, new = three_runs
    card, _ = ask(rs, "BASF")
    row = next(r for r in from_transition_plan_run(rs, new).rows if r["Company"] == "BASF SE")
    assert card.figures.model_dump() == {
        "indicators_disclosed_count": float(row["Indicators_Disclosed_Count"]),
        "walk_disclosed_count": float(row["Walk_Disclosed_Count"]),
        "talk_disclosed_count": float(row["Talk_Disclosed_Count"]),
        "walk_share_pct": float(row["Walk_Share_pct"]),
        "assessment_confidence_pct": float(row["Assessment_Confidence_pct"]),
    }


def test_older_runs_are_the_next_two_newest_first(run_store):  # AC-5
    rs = run_store
    ids = [old_run(rs, f"tp_d{i}", f"2026-0{i}-01T00:00:00+00:00", ["BASF SE"]) for i in (1, 2, 3, 4)]
    card, _ = ask(rs, "BASF")
    assert card.run_id == ids[3]
    assert [(o.run_id, o.run_date) for o in card.older_runs] == [
        (ids[2], "2026-03-01T00:00:00+00:00"), (ids[1], "2026-02-01T00:00:00+00:00"),
    ]


def test_partially_completed_counts(run_store):  # AC-6
    old_run(run_store, "tp_old", "2026-10-01T00:00:00+00:00", ["BASF SE"])
    old_run(run_store, "tp_1022", "2026-10-22T00:00:00+00:00", ["BASF SE"], status=JobStatus.PARTIALLY_COMPLETED)
    assert ask(run_store, "BASF")[0].run_id == "tp_1022"


def test_trial_runs_never_count(run_store):  # AC-7
    old_run(run_store, "tp_old", "2026-10-01T00:00:00+00:00", ["BASF SE"])
    preset_run(run_store, "2026-10-22T00:00:00+00:00", ["basf se"], params={"trial": True})
    assert ask(run_store, "BASF")[0].run_id == "tp_old"


def test_no_run_includes_company(run_store):  # AC-8
    old_run(run_store, "tp_1", "2026-10-01T00:00:00+00:00", ["Siemens AG"])
    assert ask(run_store, "BASF") == (None, "No completed transition plan assessment includes BASF.")


def _queue(rs, run_id, key, company_id):
    rs.append_review_item(run_id, {"item_key": key, "field": "tp_a_headline_1", "company_id": company_id})


def _approve(rs, run_id, key):
    append_decision(rs, run_id, ReviewDecision(
        item_key=key, decision="approve", reason_code="confirmed", reviewer=BOB.name, user_id=BOB.user_id, role=BOB.role,
        snapshot_id="s1", step="first",
    ))


def test_open_items_count_only_this_run_and_company(three_runs):  # AC-9
    rs, old, new = three_runs
    for key in ("k1", "k2", "k3"):
        _queue(rs, new, key, "basf se")
    _approve(rs, new, "k1")
    _queue(rs, new, "k4", "siemens")
    _queue(rs, old, "k5", "basf_se")
    card, text = ask(rs, "BASF")
    assert card.open_review_items == 2
    assert text.endswith(" 2 items still wait for review.")


def test_no_open_items_text(three_runs):  # AC-10
    rs, _, new = three_runs
    for key in ("k1", "k2", "k3"):
        _queue(rs, new, key, "basf se")
        _approve(rs, new, key)
    card, text = ask(rs, "BASF")
    assert card.open_review_items == 0
    assert text == f"BASF SE: newest transition plan assessment from 2026-10-20 (run {new})."


def test_exact_match_beats_contains(run_store):  # AC-11
    old_run(run_store, "tp_1", "2026-10-01T00:00:00+00:00", ["BASF", "BASF SE"])
    assert ask(run_store, "BASF")[0].company == "BASF"


def test_contains_match_on_one_company(run_store):  # AC-12
    old_run(run_store, "tp_1", "2026-10-01T00:00:00+00:00", ["BASF SE", "BASF Coatings GmbH"])
    assert ask(run_store, "BASF Coat")[0].company == "BASF Coatings GmbH"


def test_several_companies_ask_which(run_store):  # AC-13
    old_run(run_store, "tp_1", "2026-10-01T00:00:00+00:00", ["Shell plc", "Shell Midstream Partners"])
    assert ask(run_store, "Shell") == (None, 'Several companies match "Shell": Shell Midstream Partners, Shell plc. Which one do you mean?')


def test_older_runs_follow_the_chosen_company(run_store):  # AC-53
    rs = run_store
    d1 = old_run(rs, "tp_d1", "2026-01-01T00:00:00+00:00", ["BASF SE"])
    d2 = old_run(rs, "tp_d2", "2026-02-01T00:00:00+00:00", ["BASF SE"])
    old_run(rs, "tp_d3", "2026-03-01T00:00:00+00:00", ["BASF Coatings GmbH"])
    d4 = old_run(rs, "tp_d4", "2026-04-01T00:00:00+00:00", ["BASF SE"])
    card, _ = ask(rs, "BASF")
    assert card.run_id == d4 and [o.run_id for o in card.older_runs] == [d2, d1]


def test_missing_company_asks_which(run_store):  # AC-55
    old_run(run_store, "tp_1", "2026-10-01T00:00:00+00:00", ["BASF SE"])
    for company in (None, "—"):
        assert ask(run_store, company) == (None, "Which company do you mean?")


def test_accented_names_match(run_store):  # Review Focus 1
    old_run(run_store, "tp_1", "2026-10-01T00:00:00+00:00", ["Nestlé S.A.", "Siemens AG"])
    assert ask(run_store, "Nestlé")[0].company == "Nestlé S.A."


def test_empty_completed_run_is_skipped(run_store):  # Review Focus 2
    old_run(run_store, "tp_old", "2026-10-01T00:00:00+00:00", ["BASF SE"])
    old_run(run_store, "tp_empty", "2026-10-22T00:00:00+00:00", [])
    assert ask(run_store, "BASF")[0].run_id == "tp_old"


def test_accents_match_either_way(run_store):  # review I1
    old_run(run_store, "tp_1", "2026-10-01T00:00:00+00:00", ["Nestlé S.A.", "L'Oreal SA"])
    assert ask(run_store, "Nestle")[0].company == "Nestlé S.A."
    assert ask(run_store, "L'Oréal")[0].company == "L'Oreal SA"


def test_only_the_matching_run_is_built(run_store, monkeypatch):  # review I2
    import arp.ask

    old_run(run_store, "tp_1", "2026-01-01T00:00:00+00:00", ["BASF SE"])
    old_run(run_store, "tp_2", "2026-02-01T00:00:00+00:00", ["Siemens AG"])
    old_run(run_store, "tp_3", "2026-03-01T00:00:00+00:00", ["Shell plc"])
    built = []
    real = arp.ask.from_transition_plan_run
    monkeypatch.setattr(arp.ask, "from_transition_plan_run", lambda rs, run_id: built.append(run_id) or real(rs, run_id))
    assert ask(run_store, "BASF")[0].run_id == "tp_1"
    assert built == ["tp_1"]


def test_older_runs_carry_their_own_run_type(run_store):  # review M3
    old_run(run_store, "tp_old", "2026-06-01T00:00:00+00:00", ["BASF SE"])
    preset_run(run_store, "2026-10-20T00:00:00+00:00", ["basf se"])
    card, _ = ask(run_store, "BASF")
    assert card.run_type == "extraction" and [(o.run_id, o.run_type) for o in card.older_runs] == [("tp_old", "transition_plan")]


def test_a_run_that_cannot_be_read_is_skipped(run_store, monkeypatch):  # review M7
    import arp.ask

    old_run(run_store, "tp_old", "2026-06-01T00:00:00+00:00", ["BASF SE"])
    old_run(run_store, "tp_bad", "2026-10-20T00:00:00+00:00", ["BASF SE"])
    real = arp.ask.from_transition_plan_run

    def flaky(rs, run_id):
        if run_id == "tp_bad":
            raise KeyError("by_category")
        return real(rs, run_id)

    monkeypatch.setattr(arp.ask, "from_transition_plan_run", flaky)
    assert ask(run_store, "BASF")[0].run_id == "tp_old"
