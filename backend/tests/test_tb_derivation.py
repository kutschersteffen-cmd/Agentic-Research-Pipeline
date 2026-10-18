"""Derivation runs: POST /derive, GET /cells, the review items a run queues, and the current rating."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, date, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.api.auth import current_user
from arp.api.deps import get_document_content_store, get_run_store, settings_dep
from arp.api.main import app
from arp.cli import transition_barrier as cli
from arp.config import Settings, get_settings
from arp.llm import factory
from arp.storage.document_store import DocumentContentStore
from arp.storage.run_store import RunStore
from arp.transition_barrier import RUN_TYPE, clock, dataset
from arp.transition_barrier.rule_book import sign_rule_book
from tests.postgres_helpers import pg_dsn
from tests.transition_barrier_helpers import (
    A_ANALYST,
    A_APPROVER,
    B_APPROVER,
    CELL,
    FIXTURES,
    QUOTES,
    derive,
    enter_fact,
)

pytestmark = pytest.mark.usefixtures("pg")
API = "/api/transition-barrier"
D1_TITLE, D3_TITLE = "EU ETS Market Report 2026", "Steel Policy Tracker"
US = ("STL-R1", "United States")
EU = ("STL-R1", "European Union")


@pytest.fixture
def env(tmp_path, monkeypatch, pg):
    target = tmp_path / "transition_barrier"
    shutil.copytree(FIXTURES, target)
    monkeypatch.setenv("ARP_TRANSITION_BARRIER_DATA_DIR", str(target))
    get_settings.cache_clear()
    dataset.reset_caches()
    monkeypatch.setattr(clock, "today", lambda: date(2026, 10, 20))
    rs = RunStore(pg, tmp_path / "runs")
    settings = Settings(
        schema_registry_dir=tmp_path / "reg", second_review_sample_rate=0.0, bulk_accept_sample_rate=0.0,
        transition_barrier_refresh_enabled=False,
    )
    app.dependency_overrides[get_run_store] = lambda: rs
    app.dependency_overrides[get_document_content_store] = lambda: DocumentContentStore(tmp_path / "docs", dsn=pg_dsn())
    app.dependency_overrides[settings_dep] = lambda: settings
    yield rs, target
    for dep in (get_run_store, get_document_content_store, settings_dep, current_user):
        app.dependency_overrides.pop(dep, None)
    get_settings.cache_clear()
    dataset.reset_caches()


@pytest.fixture
def client(env):
    return TestClient(app)


def as_user(client, who):
    app.dependency_overrides[current_user] = lambda: who
    return client


def enter(client, fact, value, doc, page, cell=CELL, **kw):
    r = enter_fact(client, fact, value, doc, page, cell=cell, **kw)
    assert r.status_code == 201, r.text
    return r.json()


def defaults(client, cell=CELL, price=72, price_doc="D1", price_page=12):
    enter(client, "price", price, price_doc, price_page, cell=cell)
    enter(client, "applies", True, "D1", 4, cell=cell)
    enter(client, "levy", True, "D2", 3, cell=cell)


def lows(client, cell):
    """The United States / China default: price 9, no levy, entered from D3."""
    enter(client, "price", 9, "D3", 9, cell=cell)
    enter(client, "applies", True, "D3", 8, cell=cell)
    enter(client, "levy", False, "D3", 10, cell=cell)


def latest(client, cell=CELL):
    r = as_user(client, A_ANALYST).get(cell)
    assert r.status_code == 200, r.text
    return r.json()


def items(client, run_id):
    return as_user(client, A_ANALYST).get(f"/api/review/items?run_id={run_id}").json()["items"]


def price_clause(result):
    return next(c["clause"] for c in result["levels"]["H"]["conditions"] if c["fact"] == "price")


def decide(client, who, run_id, key, decision="approve"):
    c = as_user(client, who)
    etag = c.get(f"/api/review/runs/{run_id}/items/{key}/context").json()["etag"]
    reason = "confirmed" if decision == "approve" else "wrong_value"
    r = c.post(f"/api/review/runs/{run_id}/items/{key}/decision", json={"decision": decision, "reason_code": reason, "context_etag": etag})
    assert r.status_code == 200, r.text


def test_ac11_no_model_call(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a model client was built")

    for name in ("build_llm_client", "build_verifier_llm_client"):
        monkeypatch.setattr(factory, name, boom)
    for cls in (factory.LangChainAnthropicClient, factory.BatchingLLMClient, factory.GeminiClient):
        monkeypatch.setattr(cls, "__init__", boom)
    defaults(as_user(client, B_APPROVER))
    derive(as_user(client, A_ANALYST))
    assert latest(client)["latest_result"]["rating"] == "H"


def test_ac115_no_source_request(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("an HTTP request was made")

    monkeypatch.setattr(httpx.Client, "send", boom)
    monkeypatch.setattr(httpx.AsyncClient, "send", boom)
    defaults(as_user(client, B_APPROVER))
    derive(as_user(client, A_ANALYST))
    result = latest(client)["latest_result"]
    assert result["rating"] == "H" and result["notes"] == ["Sources not fetched: refresh is disabled"]


def test_refresh_on_adds_no_note(client, env):
    app.dependency_overrides[settings_dep] = lambda: Settings(transition_barrier_refresh_enabled=True)
    defaults(as_user(client, B_APPROVER))
    derive(as_user(client, A_ANALYST))
    assert latest(client)["latest_result"]["notes"] == []


def variant(env, param, **changes):
    """The fixture rule book with one parameter changed, signed as version 8."""
    path = env[1] / "rule_book.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    next(p for p in raw["criteria"]["STL-R1"]["params"] if p["id"] == param).update(changes)
    path.write_text(json.dumps(raw), encoding="utf-8")
    sign_rule_book(env[1], "owner", date(2026, 10, 18))
    dataset.reset_caches()


def test_ac18_open_threshold_is_not_rated(client, env):
    variant(env, "p_high", value=None, status="open", question="What is high?")
    defaults(as_user(client, B_APPROVER))
    derive(as_user(client, A_ANALYST))
    cell = latest(client)
    result = cell["latest_result"]
    assert (result["rating"], result["open_params"], result["rule_book_version"]) == ("not_rated", ["High price level"], 8)
    assert "Not re-derived: open threshold High price level" in cell["flags"]
    assert cell["rating"] == "H"  # the cell keeps its hand rating


def test_ac19_open_material_threshold_does_not_block_h(client, env):
    variant(env, "p_material", value=None, status="open", question="What is material?")
    defaults(as_user(client, B_APPROVER))
    derive(as_user(client, A_ANALYST))
    cell = latest(client)
    assert (cell["latest_result"]["rating"], cell["flags"]) == ("H", [])


def conflict(client):
    b = as_user(client, B_APPROVER)
    d1 = enter(b, "price", 72, "D1", 12)
    enter(b, "price", 30, "D3", 7)
    enter(b, "applies", True, "D1", 4)
    enter(b, "levy", True, "D2", 3)
    return d1["id"]


def test_ac37_conflict_item_lists_values_in_order(client):
    conflict(client)
    run_id = derive(as_user(client, A_ANALYST))
    assert latest(client)["latest_result"]["rating"] == "conflict"
    [item] = items(client, run_id)
    assert item["kind"] == "barrier_cell"
    assert item["payload"]["kind"] == "conflict" and item["payload"]["proposed"] is None
    assert item["payload"]["values"] == [f"72 USD/tCO2, {D1_TITLE}", f"30 USD/tCO2, {D3_TITLE}"]


def choose(client, d1_id):
    r = as_user(client, A_ANALYST).post(f"{CELL}/choices", json={"fact": "price", "value_id": d1_id, "reason": "newer data"})
    assert r.status_code == 201, r.text
    return r.json()


def test_ac51_ac53_ac139_choice(client):
    d1_id = conflict(client)
    derive(as_user(client, A_ANALYST))
    out = choose(client, d1_id)  # the choice alone re-derives the cell
    result = latest(client)["latest_result"]
    assert result["run_id"] == out["run_id"]
    assert result["rating"] == "H"
    assert price_clause(result) == f"Effective carbon price = 72 USD/tCO2 ({D1_TITLE}, p. 12): pass."  # AC-51
    derive(as_user(client, A_ANALYST))
    assert latest(client)["latest_result"]["rating"] == "H"  # AC-53
    enter(as_user(client, B_APPROVER), "price", 40, "D3", 11)  # a new value lifts the choice
    derive(as_user(client, A_ANALYST))
    assert latest(client)["latest_result"]["rating"] == "conflict"  # AC-139


def test_ac54_ac55_change_is_queued_not_applied(client):
    defaults(as_user(client, B_APPROVER), price=30, price_page=13)
    run_id = derive(as_user(client, A_ANALYST))
    scores = as_user(client, A_ANALYST).get(f"{API}/scores", params={"sector": "Steel", "region": "European Union"}).json()
    assert [(s["code"], s["rating"]) for s in scores] == [("STL-R1", "H")]
    cell = latest(client)
    assert (cell["rating"], cell["basis"], cell["ratified_by"]) == ("H", "hand_rated", None)
    assert cell["latest_result"]["rating"] == "M"
    [item] = items(client, run_id)
    p = item["payload"]
    assert (item["kind"], p["kind"], p["current"], p["proposed"]) == ("barrier_cell", "changed", "H", "M")
    assert (p["entered_by"], p["rule_book_version"], p["code"], p["region"]) == (["b.approver"], 7, "STL-R1", "European Union")


def test_result_values_carry_their_quote(client):
    defaults(as_user(client, B_APPROVER), price=30, price_page=13)
    derive(as_user(client, A_ANALYST))
    values = {v["fact"]: v for v in latest(client)["latest_result"]["values"]}
    assert values["price"]["quote"] == QUOTES["D1"][13]


def test_unchanged_item(client):
    defaults(as_user(client, B_APPROVER))
    [item] = items(client, derive(as_user(client, A_ANALYST)))
    assert (item["payload"]["kind"], item["payload"]["current"], item["payload"]["proposed"]) == ("unchanged", "H", "H")


def test_not_rated_item_proposes_nothing(client):
    enter(as_user(client, B_APPROVER), "applies", True, "D1", 4)
    [item] = items(client, derive(as_user(client, A_ANALYST)))
    assert (item["payload"]["kind"], item["payload"]["proposed"]) == ("not_rated", None)


def test_run_finishes_with_one_result_and_item_per_cell(client, env):
    defaults(as_user(client, B_APPROVER))
    lows(as_user(client, B_APPROVER), CELL.replace("European Union", "United States"))
    run_id = derive(as_user(client, A_ANALYST), [EU, US, EU])
    manifest = env[0].load_manifest(run_id)
    assert (manifest.run_type, manifest.status.value, manifest.company_count, manifest.completed_count) == (RUN_TYPE, "completed", 2, 2)
    assert [r["_key"] for r in env[0].read_results(run_id)] == ["STL-R1:European Union", "STL-R1:United States"]
    assert sorted(i["item_key"] for i in items(client, run_id)) == ["STL-R1:European Union", "STL-R1:United States"]


def test_latest_result_is_null_before_any_run(client):
    cell = latest(client)
    assert (cell["rating"], cell["basis"], cell["latest_result"], cell["flags"]) == ("H", "hand_rated", None, [])
    assert cell["history"] == [{"at": "2026-08-14", "by": None, "kind": "rating", "rating": "H", "basis": "hand_rated"}]
    assert cell["last_verified"] == "2026-08-14"


def test_ratified_change_becomes_current(client):
    defaults(as_user(client, B_APPROVER), price=30, price_page=13)
    run_id = derive(as_user(client, A_ANALYST))
    decide(client, A_ANALYST, run_id, "STL-R1:European Union")
    assert latest(client)["rating"] == "H"  # one approval is not enough for a rating change
    decide(client, A_APPROVER, run_id, "STL-R1:European Union")
    cell = latest(client)
    assert (cell["rating"], cell["basis"], cell["ratified_by"], cell["confidence"]) == ("M", "derived", "a.approver", "high")
    assert cell["source"] == f"{D1_TITLE}; CBAM Regulation 2023/956"
    assert cell["evidence"] == cell["latest_result"]["levels"]["H"]["detail"] + " " + cell["latest_result"]["levels"]["M"]["detail"]
    assert cell["last_verified"] == datetime.now(UTC).date().isoformat()  # the day a.approver decided


def test_rejected_result_changes_nothing(client):
    defaults(as_user(client, B_APPROVER), price=30, price_page=13)
    run_id = derive(as_user(client, A_ANALYST))
    decide(client, A_APPROVER, run_id, "STL-R1:European Union", "reject")
    cell = latest(client)
    assert (cell["rating"], cell["basis"], cell["last_verified"]) == ("H", "hand_rated", "2026-08-14")


def test_approved_not_rated_ratifies_nothing(client):
    enter(as_user(client, B_APPROVER), "applies", True, "D1", 4)
    run_id = derive(as_user(client, A_ANALYST))
    decide(client, A_ANALYST, run_id, "STL-R1:European Union")
    assert (latest(client)["basis"], latest(client)["rating"]) == ("hand_rated", "H")


def test_newest_final_decision_wins(client):
    defaults(as_user(client, B_APPROVER))  # price 72: H, unchanged
    older = derive(as_user(client, A_ANALYST))
    enter(as_user(client, B_APPROVER), "price", "72.005", "D1", 15)  # still H, from another figure
    newer = derive(as_user(client, A_ANALYST))
    for run_id in (newer, older):  # the older item is approved last, so its decision is the latest
        decide(client, A_ANALYST, run_id, "STL-R1:European Union")  # `unchanged`, both derived from H: allowed
    cell = latest(client)
    assert price_clause(cell["latest_result"]) == f"Effective carbon price = 72.01 USD/tCO2 ({D1_TITLE}, p. 15): pass."
    assert f"Effective carbon price = 72 USD/tCO2 ({D1_TITLE}, p. 12)" in cell["evidence"]


def test_unknown_cell_404(client):
    c = as_user(client, A_ANALYST)
    for code, region in (("NOPE-R1", "European Union"), ("STL-R1", "Mars")):
        want = {"detail": f"Unknown cell {code} / {region}"}
        r = c.post(f"{API}/derive", json={"cells": [{"code": "STL-R1", "region": "European Union"}, {"code": code, "region": region}]})
        assert (r.status_code, r.json()) == (404, want)
        r = c.get(f"{API}/cells/{code}/{region}")
        assert (r.status_code, r.json()) == (404, want)
    assert c.get(f"{API}/cells/STL-R1/European%20Union").status_code == 200
    assert c.post(f"{API}/derive", json={"cells": []}).status_code == 422


def test_failed_derivation_marks_the_run_failed(client, env, monkeypatch):
    from arp.transition_barrier import derivation

    def boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr(derivation.store, "cell_values", boom)
    r = as_user(client, A_ANALYST).post(f"{API}/derive", json={"cells": [{"code": "STL-R1", "region": "European Union"}]})
    assert r.status_code >= 500
    [m] = env[0].list_runs(RUN_TYPE)
    assert (m.status.value, m.error) == ("failed", "store down")


def test_cli_derive_prints_run_id(env, monkeypatch):
    monkeypatch.setattr(cli, "_run_store", lambda: env[0])
    runner = CliRunner()
    out = runner.invoke(cli.transition_barrier_app, ["derive", "--code", "STL-R1", "--region", "European Union", "--now", "2026-10-20"])
    assert out.exit_code == 0, out.output
    run_id = out.output.strip()
    assert env[0].load_manifest(run_id).run_type == RUN_TYPE and env[0].read_results(run_id)[0]["rating"] == "not_rated"
    bad = runner.invoke(cli.transition_barrier_app, ["derive", "--code", "STL-R1", "--region", "Mars"])
    assert (bad.exit_code, bad.output.strip()) == (1, "Unknown cell STL-R1 / Mars")
    bad = runner.invoke(cli.transition_barrier_app, ["derive", "--code", "STL-R1", "--region", "China", "--now", "20.10.2026"])
    assert (bad.exit_code, bad.output.strip()) == (1, "--now must be YYYY-MM-DD.")
