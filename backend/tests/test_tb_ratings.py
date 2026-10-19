"""Current ratings, flags and history on every reader: /scores, /matrix and /cells."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from arp.api.deps import settings_dep
from arp.api.main import app
from arp.config import Settings, get_settings
from arp.transition_barrier import dataset, ratings
from arp.transition_barrier.rule_book import sign_rule_book
from tests.test_tb_derivation import (  # noqa: F401  (env is a fixture)
    API,
    CELL,
    D1_TITLE,
    EU,
    US,
    as_user,
    decide,
    defaults,
    enter,
    env,
    latest,
    variant,
)
from tests.transition_barrier_helpers import A_ANALYST, A_APPROVER, B_ANALYST, B_APPROVER, derive

pytestmark = pytest.mark.usefixtures("pg")
KEY = "STL-R1:European Union"
CHINA = CELL.replace("European Union", "China")
UNITED_STATES = CELL.replace("European Union", "United States")
H_PREFIX = "H: Effective carbon price >= 50 USD/tCO2"
AC59 = (
    "H: Effective carbon price >= 50 USD/tCO2 and Border levy in force is Yes. "
    f"Effective carbon price = 30 USD/tCO2 ({D1_TITLE}, p. 13): fail. "
    "Border levy in force = Yes (CBAM Regulation 2023/956, p. 3): pass. "
    "M: Carbon price applies to steel is Yes and Effective carbon price >= 10 USD/tCO2. "
    f"Carbon price applies to steel = Yes ({D1_TITLE}, p. 4): pass. "
    f"Effective carbon price = 30 USD/tCO2 ({D1_TITLE}, p. 13): pass."
)


@pytest.fixture
def client(env, monkeypatch, tmp_path):  # noqa: F811
    """/scores and /matrix build their own run store from the settings, so point it at the test's runs."""
    monkeypatch.setattr(get_settings(), "runs_dir", tmp_path / "runs")
    return TestClient(app)


def scores(client, **params):
    r = as_user(client, A_ANALYST).get(f"{API}/scores", params={"sector": "Steel", "region": "European Union", **params})
    assert r.status_code == 200, r.text
    [score] = r.json()
    return score


def ratify_change(client, price=30, page=13):
    """AC-55 to AC-57: price 30 gives a `changed` item; a.analyst approves, a.approver confirms."""
    defaults(as_user(client, B_APPROVER), price=price, price_page=page)
    run_id = derive(as_user(client, A_ANALYST))
    decide(client, A_ANALYST, run_id, KEY)
    return run_id


def test_ac56_to_ac59_ratified_cell_on_scores(client):
    run_id = ratify_change(client)
    assert scores(client)["rating"] == "H"  # AC-56
    decide(client, A_APPROVER, run_id, KEY)
    s = scores(client)
    assert (s["rating"], s["basis"], s["ratified_by"], s["flags"]) == ("M", "derived", "a.approver", [])  # AC-57
    assert s["last_verified"] == datetime.now(UTC).date().isoformat()
    assert (s["confidence"], s["source"]) == ("high", f"{D1_TITLE}; CBAM Regulation 2023/956")  # AC-58
    assert s["evidence"] == AC59
    matrix = as_user(client, A_ANALYST).get(f"{API}/matrix").json()
    assert matrix["cells"]["STL-R1"]["European Union"]["rating"] == "M"
    assert matrix["distribution"]["overall"] == {"H": 0, "M": 1, "L": 2}


def test_ac63_rejected_change_leaves_hand_rating(client):
    defaults(as_user(client, B_APPROVER), price=30, price_page=13)
    run_id = derive(as_user(client, A_ANALYST))
    decide(client, A_APPROVER, run_id, KEY, "reject")
    s = scores(client)
    assert (s["rating"], s["basis"], s["ratified_by"]) == ("H", "hand_rated", None)


def test_ac65_bulk_accept_ratifies_each_cell(client):
    b = as_user(client, B_ANALYST)
    eu = [("price", 72, "D1", 12), ("applies", True, "D1", 4), ("levy", True, "D2", 3)]
    low = [("price", 9, "D3", 9), ("applies", True, "D3", 8), ("levy", False, "D3", 10)]
    for cell, rows in ((CELL, eu), (UNITED_STATES, low), (CHINA, low)):
        for row in rows:
            enter(b, *row, cell=cell, as_user=B_ANALYST)
    run_id = derive(as_user(client, A_ANALYST), [EU, US, ("STL-R1", "China")])
    c = as_user(client, A_ANALYST)
    keys = [f"STL-R1:{r}" for r in ("European Union", "United States", "China")]
    items = [{"item_key": k, "context_etag": c.get(f"/api/review/runs/{run_id}/items/{k}/context").json()["etag"]} for k in keys]
    r = c.post("/api/extraction/items/bulk-accept", json={"run_id": run_id, "items": items})
    assert r.status_code == 200 and r.json()["accepted"] == 3, r.text
    got = as_user(client, A_ANALYST).get(f"{API}/scores", params={"sector": "Steel"}).json()
    assert [(s["basis"], s["ratified_by"]) for s in got] == [("derived", "a.analyst")] * 3


def test_ac52_choice_in_history(client):
    b = as_user(client, B_APPROVER)
    d1 = enter(b, "price", 72, "D1", 12)
    enter(b, "price", 30, "D3", 7)
    r = as_user(client, A_ANALYST).post(f"{CELL}/choices", json={"fact": "price", "value_id": d1["id"], "reason": "newer data"})
    assert r.status_code == 201, r.text
    history = latest(client)["history"]
    [choice] = [e for e in history if e["kind"] == "choice"]
    assert (choice["by"], choice["value"], choice["reason"]) == ("a.analyst", f"72 USD/tCO2, {D1_TITLE}", "newer data")
    assert [(e["by"], e["value"]) for e in history if e["kind"] == "fact"] == [
        ("b.approver", f"72 USD/tCO2, {D1_TITLE}"), ("b.approver", "30 USD/tCO2, Steel Policy Tracker"),
    ]
    assert [e["at"] for e in history] == sorted(e["at"] for e in history)


def test_ac68_history_lists_every_ratified_rating(client):
    decide(client, A_APPROVER, ratify_change(client), KEY)  # M
    enter(as_user(client, B_APPROVER), "price", 9, "D1", 16)
    run_id = derive(as_user(client, A_ANALYST))
    decide(client, A_ANALYST, run_id, KEY)
    decide(client, A_APPROVER, run_id, KEY)  # L
    history = latest(client)["history"]
    ratings = [(e["rating"], e["basis"], e["by"], e["at"] if e["by"] is None else None) for e in history if e["kind"] == "rating"]
    assert ratings == [("H", "hand_rated", None, "2026-08-14"), ("M", "derived", "a.approver", None), ("L", "derived", "a.approver", None)]
    decisions = [(e["by"], e["decision"]) for e in history if e["kind"] == "decision"]
    assert decisions == [("a.analyst", "approve"), ("a.approver", "approve")] * 2
    assert latest(client)["rating"] == "L"


def not_rated_cell(client):
    """AC-4: `applies` and `levy` are known, `price` has no counted value."""
    b = as_user(client, B_APPROVER)
    enter(b, "applies", True, "D1", 4)
    enter(b, "levy", True, "D2", 3)
    return derive(as_user(client, A_ANALYST))


def test_ac69_ac70_not_rated_flag_survives_dismissal(client):
    run_id = not_rated_cell(client)
    cell = latest(client)
    assert (cell["rating"], cell["basis"]) == ("H", "hand_rated")
    assert cell["flags"] == ["Not re-derived: missing Effective carbon price"]
    assert scores(client)["flags"] == cell["flags"]
    decide(client, A_ANALYST, run_id, KEY, "reject")  # AC-70
    cell = latest(client)
    assert (cell["rating"], cell["flags"]) == ("H", ["Not re-derived: missing Effective carbon price"])


def test_ac140_flag_clears_when_a_later_derivation_rates(client):
    not_rated_cell(client)
    enter(as_user(client, B_APPROVER), "price", 72, "D1", 12)
    derive(as_user(client, A_ANALYST))  # its item is not decided
    assert latest(client)["flags"] == []
    assert scores(client)["flags"] == []


def test_ac72_ac73_ac141_rules_changed_flag(client, env):  # noqa: F811
    decide(client, A_APPROVER, ratify_change(client), KEY)
    variant(env, "p_high", value=60)  # version 8; reset_caches stands in for the restart
    cell = latest(client)
    assert cell["flags"] == ["Rules changed since this rating (v7)"]  # AC-72
    assert scores(client)["flags"] == cell["flags"]
    assert cell["evidence"].startswith(H_PREFIX)  # AC-73: the ratified result keeps the rules it was derived with
    run_id = derive(as_user(client, A_ANALYST))
    assert latest(client)["flags"] == ["Rules changed since this rating (v7)"]  # AC-141
    decide(client, A_ANALYST, run_id, KEY)  # `unchanged`: one analyst is enough
    cell = latest(client)
    assert (cell["flags"], cell["evidence"].startswith("H: Effective carbon price >= 60 USD/tCO2")) == ([], True)


def test_staleness_counts_from_the_decision_date(client):
    decide(client, A_APPROVER, ratify_change(client), KEY)
    app.dependency_overrides[settings_dep] = lambda: Settings(transition_barrier_staleness_days=30)
    report = as_user(client, A_ANALYST).get(f"{API}/staleness").json()
    # the two hand-rated cells (verified 2026-08-14) are stale; the ratified one counts from today
    assert (report["total"], report["stale"], report["fresh"]) == (3, 2, 1)
    cell = as_user(client, A_ANALYST).get(f"{API}/matrix").json()["cells"]["STL-R1"]
    assert [cell[r]["stale"] for r in ("European Union", "United States", "China")] == [False, True, True]


def test_source_comes_from_the_ratified_snapshot(client, env):  # noqa: F811
    decide(client, A_APPROVER, ratify_change(client), KEY)
    variant(env, "p_high", value=60)
    assert scores(client)["source"] == f"{D1_TITLE}; CBAM Regulation 2023/956"


def test_stale_item_does_not_roll_back(client):
    """Review Focus 5. The newest final decision wins (Ruling 11), so an older run's item only
    takes the cell back with a final decision of its own, and a reject never does."""
    defaults(as_user(client, B_APPROVER), price=30, price_page=13)
    older = derive(as_user(client, A_ANALYST))
    enter(as_user(client, B_APPROVER), "price", 9, "D1", 16)
    newer = derive(as_user(client, A_ANALYST))
    decide(client, A_ANALYST, newer, KEY)
    decide(client, A_APPROVER, newer, KEY)
    assert latest(client)["latest_result"]["rating"] == "L" and scores(client)["rating"] == "L"
    r = attempt(client, A_ANALYST, older)  # derived when the cell was H; it is L now
    assert (r.status_code, r.json()["detail"]) == (409, STALE)
    assert scores(client)["rating"] == "L"
    decide(client, A_APPROVER, older, KEY, "reject")
    assert scores(client)["rating"] == "L"


def test_older_item_decided_before_the_newer_one_loses(client):
    defaults(as_user(client, B_APPROVER), price=30, price_page=13)
    older = derive(as_user(client, A_ANALYST))
    enter(as_user(client, B_APPROVER), "price", 9, "D1", 16)
    newer = derive(as_user(client, A_ANALYST))
    decide(client, A_ANALYST, older, KEY)
    decide(client, A_APPROVER, older, KEY)
    r = attempt(client, A_ANALYST, newer)  # derived when the cell was H; it is M now
    assert (r.status_code, r.json()["detail"]) == (409, STALE)
    again = derive(as_user(client, A_ANALYST))  # M -> L
    decide(client, A_ANALYST, again, KEY)
    decide(client, A_APPROVER, again, KEY)
    assert scores(client)["rating"] == "L"


@pytest.fixture
def bundled(pg, monkeypatch, tmp_path):
    """The shipped data directory, with a database so /scores reads ratings the way production does."""
    monkeypatch.setenv("ARP_RUNS_DIR", str(tmp_path / "runs"))
    get_settings.cache_clear()
    dataset.reset_caches()
    yield TestClient(app)
    get_settings.cache_clear()
    dataset.reset_caches()


NEW = {"basis": "hand_rated", "ratified_by": None, "flags": []}


def test_ac130_hand_rated_scores_equal_bundled(bundled):
    got = bundled.get(f"{API}/scores").json()
    want = [s.model_dump(mode="json") for s in dataset.load_scores()]
    assert len(got) == 105 and got == [{**w, **NEW} for w in want]


def test_ac131_hand_rated_matrix_cells(bundled):
    cells = bundled.get(f"{API}/matrix").json()["cells"]
    for s in dataset.load_scores():
        cell = cells[s.code][s.region.value]
        assert {k: cell[k] for k in s.model_dump(mode="json")} == {**s.model_dump(mode="json"), **NEW}


STALE = "the cell's rating changed since this result; derive again"
FINAL = "this item is final; derive the cell again"


def attempt(client, who, run_id, decision="approve"):
    """One decision on the cell's item in `run_id`, returned as the response (the caller checks the status)."""
    c = as_user(client, who)
    etag = c.get(f"/api/review/runs/{run_id}/items/{KEY}/context").json()["etag"]
    reason = "confirmed" if decision == "approve" else "wrong_value"
    return c.post(f"/api/review/runs/{run_id}/items/{KEY}/decision", json={"decision": decision, "reason_code": reason, "context_etag": etag})


def bulk(client, who, run_id):
    c = as_user(client, who)
    etag = c.get(f"/api/review/runs/{run_id}/items/{KEY}/context").json()["etag"]
    r = c.post("/api/extraction/items/bulk-accept", json={"run_id": run_id, "items": [{"item_key": KEY, "context_etag": etag}]})
    assert r.status_code == 200, r.text
    return r.json()


def stale_unchanged_item(client):
    """An `unchanged` H item, then a newer `changed` H -> M item that a.analyst and a.approver ratify."""
    defaults(as_user(client, B_APPROVER))  # price 72: H, unchanged
    older = derive(as_user(client, A_ANALYST))
    enter(as_user(client, B_APPROVER), "price", 30, "D1", 13)  # replaces the D1 price
    newer = derive(as_user(client, A_ANALYST))
    decide(client, A_ANALYST, newer, KEY)
    decide(client, A_APPROVER, newer, KEY)
    assert scores(client)["rating"] == "M"
    return older


def test_stale_unchanged_item_cannot_undo_a_ratified_change(client):
    older = stale_unchanged_item(client)
    r = attempt(client, B_ANALYST, older)
    assert (r.status_code, r.json()["detail"]) == (409, STALE)
    assert attempt(client, B_ANALYST, older, "reject").status_code == 200  # a reject changes nothing
    s = scores(client)
    assert (s["rating"], s["basis"], s["ratified_by"]) == ("M", "derived", "a.approver")


def test_bulk_accept_refuses_a_stale_unchanged_item(client):
    older = stale_unchanged_item(client)
    assert bulk(client, B_ANALYST, older) == {"accepted": 0, "second_review": [], "refused": [{"item_key": KEY, "reason": STALE}]}
    s = scores(client)
    assert (s["rating"], s["ratified_by"]) == ("M", "a.approver")


def test_a_final_item_is_not_decided_again(client):
    run_id = ratify_change(client)
    decide(client, A_APPROVER, run_id, KEY)
    for who, decision in ((B_ANALYST, "reject"), (A_APPROVER, "approve")):
        r = attempt(client, who, run_id, decision)
        assert (r.status_code, r.json()["detail"]) == (409, FINAL)
    assert bulk(client, B_ANALYST, run_id) == {"accepted": 0, "second_review": [], "refused": [{"item_key": KEY, "reason": FINAL}]}
    s = scores(client)
    assert (s["rating"], s["basis"], s["ratified_by"]) == ("M", "derived", "a.approver")


def test_matrix_distribution_counts_its_own_cells(client):
    decide(client, A_APPROVER, ratify_change(client), KEY)
    matrix = as_user(client, A_ANALYST).get(f"{API}/matrix").json()
    by_region = {r: Counter(c[r]["rating"] for c in matrix["cells"].values()) for r in matrix["regions"]}
    overall = sum(by_region.values(), Counter())
    assert matrix["distribution"]["overall"] == {k: overall[k] for k in "HML"}
    assert all(matrix["distribution"][r] == {k: n[k] for k in "HML"} for r, n in by_region.items())
    assert matrix["cells"]["STL-R1"]["European Union"]["rating"] == "M"


def test_one_ratings_pass_per_request(client, monkeypatch):
    built = []
    real = ratings.Ratings.__init__
    monkeypatch.setattr(ratings.Ratings, "__init__", lambda self, rs: (built.append(1), real(self, rs))[1])
    derive(as_user(client, A_ANALYST), [EU, US, ("STL-R1", "China")])
    assert len(built) == 1
    built.clear()
    assert as_user(client, A_ANALYST).get(f"{API}/matrix").status_code == 200
    assert len(built) == 1


def test_signing_without_changing_the_criterion_flags_nothing(client, env):  # noqa: F811
    decide(client, A_APPROVER, ratify_change(client), KEY)
    assert sign_rule_book(env[1], "owner", date(2026, 10, 18)) == 8  # STL-R1's rules are as they were
    dataset.reset_caches()
    assert latest(client)["flags"] == []
