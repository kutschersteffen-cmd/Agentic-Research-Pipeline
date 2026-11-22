"""Agent board draws, slice 2 (spec docs/superpowers/specs/2026-11-22-agent-board.md, AC-14 to AC-20b)."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.agent_board.draw import build_prompt
from arp.agent_board.store import BoardStore
from arp.api.routers import agent_board
from arp.orchestration.plan_store import PlanStore
from arp.standins import StandInLLMClient

SCRIPT = 'u = universe_build(taxonomy_id="t", source="u.csv")\n'
BAR_C = {"mark": "bar", "data": {"values": [{"s": "Energy", "w": 0.125}, {"s": "Utilities", "w": 0.31}]},
         "encoding": {"x": {"field": "s", "type": "nominal"}, "y": {"field": "w", "type": "quantitative"}}}
FLOW_F = "flowchart LR\n  a[Build universe] --> b[Extract]\n  b --> c[Report]"
FLOW_X = "flowchart RL\n  a --> b"
WEIGHTS = {"weights": [{"sector": "Energy", "weight": 0.125}, {"sector": "Utilities", "weight": 0.31}]}


@pytest.fixture
def store(pg):
    return BoardStore(pg)


@pytest.fixture
def plan(pg):
    """Done plan D."""
    plans = PlanStore(pg)
    plan_id = plans.create("b", SCRIPT)
    plans.set_status(plan_id, "done")
    plans.record_call(plan_id, seq=1, kind="index_construct", params={}, status="done")
    plans.update_call(plan_id, 1, result=WEIGHTS)
    return plan_id


@pytest.fixture
def client(store, tmp_path):
    app = FastAPI()
    app.include_router(agent_board.router)
    app.dependency_overrides[agent_board.board_store] = lambda: store
    app.dependency_overrides[agent_board.draw_llm] = lambda: lambda: StandInLLMClient(tmp_path)
    with TestClient(app) as c:
        yield c


def _b(plan):
    return f"/api/agent/boards/plan/{plan}"


def _standin(folder, data):
    (folder / "model").mkdir(exist_ok=True)
    (folder / "model" / "BoardBlockDraft.json").write_text(json.dumps(data))


def _calls(folder):
    path = folder / "calls.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def _draw(client, plan, tmp_path, draft, **body):
    _standin(tmp_path, {"output": draft})
    return client.post(f"{_b(plan)}/draw", json={"prompt": "x", **body})


def test_draw_chart(client, plan, tmp_path):  # AC-14, AC-15
    _standin(tmp_path, {"output": {"kind": "chart", "title": "Weights", "source": BAR_C}})
    res = client.post(f"{_b(plan)}/draw", json={"prompt": "chart the weights"})
    assert res.status_code == 200, res.text
    b = res.json()
    assert (b["origin"], b["kind"], b["position"], b["unverified"]) == ("agent", "chart", 0, [])
    assert b["rendered"]["light"].startswith("<svg")
    calls = _calls(tmp_path)
    assert [c["name"] for c in calls] == ["BoardBlockDraft"]
    assert calls[0]["prompt"].startswith('Request: chart the weights\n\nThread data:\n{"brief":')
    assert '"weight":0.125' in calls[0]["prompt"]


def test_board_never_changes_the_plan(client, plan, pg, tmp_path):  # AC-14b
    plans = PlanStore(pg)
    plan_before, calls_before = plans.get(plan), plans.calls(plan)
    n = client.post(f"{_b(plan)}/blocks", json={"kind": "note", "title": "N", "source": "a"}).json()["id"]
    client.patch(f"{_b(plan)}/blocks/{n}", json={"source": "b"})
    client.post(f"{_b(plan)}/blocks/{n}/undo")
    client.delete(f"{_b(plan)}/blocks/{n}")
    assert _draw(client, plan, tmp_path, {"kind": "note", "title": "S", "source": "s"}).status_code == 200
    assert (plans.get(plan), plans.calls(plan)) == (plan_before, calls_before)


def test_retry_after_a_refused_draft(client, plan, tmp_path):  # AC-16
    _standin(tmp_path, [{"output": {"kind": "flow", "title": "P", "source": FLOW_X}},
                        {"output": {"kind": "flow", "title": "P", "source": FLOW_F}}])
    res = client.post(f"{_b(plan)}/draw", json={"prompt": "draw the plan"})
    assert (res.status_code, res.json()["kind"]) == (200, "flow")
    calls = _calls(tmp_path)
    assert len(calls) == 2
    assert "Your last answer was refused: " not in calls[0]["prompt"]
    assert calls[1]["prompt"].endswith(
        "\n\nYour last answer was refused: line 1: direction RL is not supported; use LR or TB")


def test_two_refused_drafts(client, plan, tmp_path):  # AC-16b
    bad = {"output": {"kind": "chart", "title": "W", "source": {"data": {"url": "x"}}}}
    _standin(tmp_path, [bad, bad])
    res = client.post(f"{_b(plan)}/draw", json={"prompt": "x"})
    assert (res.status_code, res.json()) == (
        422, {"detail": "the agent could not draw this: chart may not load from outside: data.url"})
    assert client.get(_b(plan)).json()["blocks"] == []


def test_model_call_fails(client, plan, tmp_path):  # AC-16c
    _standin(tmp_path, {"error": "boom"})
    res = client.post(f"{_b(plan)}/draw", json={"prompt": "x"})
    assert (res.status_code, res.json()) == (502, {"detail": "the agent could not draw this: model call failed"})
    assert client.get(_b(plan)).json()["blocks"] == []


def test_full_board_makes_no_call(client, plan, store, tmp_path):  # AC-16d
    for i in range(50):
        store.create("plan", plan, "note", f"N{i}", "a")
    res = _draw(client, plan, tmp_path, {"kind": "note", "title": "S", "source": "s"})
    assert (res.status_code, res.json()) == (409, {"detail": "board is full (50 blocks)"})
    assert _calls(tmp_path) == []


def test_number_check_on_a_table(client, plan, tmp_path):  # AC-17, AC-17b
    table = {"columns": ["sector", "weight"], "rows": [["Energy", 0.125], ["Utilities", 0.31], ["Total", 0.435]]}
    b = _draw(client, plan, tmp_path, {"kind": "table", "title": "T", "source": table}).json()
    assert b["unverified"] == [0.435]
    res = client.patch(f"{_b(plan)}/blocks/{b['id']}", json={"title": "Weights table"}).json()
    assert (res["version"], res["origin"], res["unverified"]) == (2, "agent", [0.435])


def test_number_check_on_a_layered_chart(client, plan, tmp_path):  # AC-17c
    chart = {"layer": [{"mark": "bar", "data": {"values": [{"w": 0.31}, {"w": 0.77}]},
                        "encoding": {"y": {"field": "w", "type": "quantitative"}}}]}
    assert _draw(client, plan, tmp_path, {"kind": "chart", "title": "L", "source": chart}).json()["unverified"] == [0.77]


def test_number_check_on_a_persons_edit(client, plan):  # AC-17d
    t = client.post(f"{_b(plan)}/blocks", json={"kind": "table", "title": "T",
                                                "source": {"columns": ["a", "b"], "rows": [["x", 0.125]]}}).json()
    res = client.patch(f"{_b(plan)}/blocks/{t['id']}", json={"source": {"columns": ["a", "b"], "rows": [["x", 9.99]]}})
    assert (res.json()["origin"], res.json()["unverified"]) == ("person", [9.99])


def test_number_check_ignores_strings_and_booleans(client, plan, tmp_path):
    table = {"columns": ["a", "b"], "rows": [["1.5", 0.12499], [None, 1]]}  # 1: the call's seq
    assert _draw(client, plan, tmp_path, {"kind": "table", "title": "T", "source": table}).json()["unverified"] == []
    chart = {"mark": "bar", "data": {"values": [{"s": "7", "b": True, "w": 0.31}]}, "datasets": {"d": [{"w": 0.125}]},
             "encoding": {"y": {"field": "w", "type": "quantitative"}, "x": {"value": 4}}}
    assert _draw(client, plan, tmp_path, {"kind": "chart", "title": "C", "source": chart}).json()["unverified"] == []


def test_redraw_and_undo(client, plan, tmp_path):  # AC-19, AC-19b
    a = _draw(client, plan, tmp_path, {"kind": "chart", "title": "Weights", "source": BAR_C}).json()
    res = _draw(client, plan, tmp_path, {"kind": "table", "title": "W", "source": {"columns": ["s"], "rows": [["Energy"]]}},
                block_id=a["id"])
    assert res.status_code == 200
    b = res.json()
    assert (b["id"], b["position"], b["kind"], b["version"], b["origin"]) == (a["id"], 0, "table", 2, "agent")
    assert 'Current block: {"kind":"chart"' in _calls(tmp_path)[-1]["prompt"]
    u = client.post(f"{_b(plan)}/blocks/{a['id']}/undo").json()
    assert (u["kind"], u["version"], u["source"]) == ("chart", 3, BAR_C)


def test_redraw_of_a_block_on_another_board(client, plan, pg, store, tmp_path):
    other = PlanStore(pg).create("o", SCRIPT)
    x = store.create("plan", other, "note", "X", "a")
    res = _draw(client, plan, tmp_path, {"kind": "note", "title": "S", "source": "s"}, block_id=x["id"])
    assert (res.status_code, res.json()) == (404, {"detail": "block not found"})
    assert _calls(tmp_path) == []


@pytest.mark.parametrize("prompt", ["   ", "x" * 2001, 3, None])
def test_prompt_refused_without_a_call(client, plan, tmp_path, prompt):  # AC-20
    res = client.post(f"{_b(plan)}/draw", json={"prompt": prompt})
    assert (res.status_code, res.json()) == (422, {"detail": "prompt must be 1 to 2000 characters"})
    assert _calls(tmp_path) == []


def test_draw_on_unknown_thread(client, pg, tmp_path):
    res = client.post("/api/agent/boards/plan/nope/draw", json={"prompt": "x"})
    assert (res.status_code, res.json()) == (404, {"detail": "thread not found"})
    assert _calls(tmp_path) == []


def test_thread_data_truncated():  # AC-20b
    data = {"brief": "b", "status": "done", "steps": [{"seq": 1, "result": {"t": "é" * 15000}}]}
    prompt = build_prompt("x", data)
    head, tail = prompt.split("Thread data:\n", 1)
    assert tail.endswith("\n(thread data truncated at 20000 bytes)")
    body = tail.removesuffix("\n(thread data truncated at 20000 bytes)")
    assert len(body.encode("utf-8")) <= 20000
    assert len(body.encode("utf-8")) >= 19999  # the longest prefix of whole characters
    assert json.dumps(data, ensure_ascii=False, separators=(",", ":")).startswith(body)


def test_thread_data_not_truncated_when_it_fits():
    assert build_prompt("x", {"a": 1}) == 'Request: x\n\nThread data:\n{"a":1}'


@pytest.mark.parametrize("bad", [
    {"kind": "note", "title": "T", "source": "a\x00b"},
    {"kind": "table", "title": "T", "source": {"columns": ["a"], "rows": [[float("nan")]]}},
])
def test_unstorable_draft_is_refused_and_retried(client, plan, tmp_path, bad):
    _standin(tmp_path, [{"output": bad}, {"output": bad}])
    res = client.post(f"{_b(plan)}/draw", json={"prompt": "x"})
    assert (res.status_code, res.json()) == (422, {"detail": "the agent could not draw this: invalid block"})
    calls = _calls(tmp_path)
    assert len(calls) == 2 and calls[1]["prompt"].endswith("Your last answer was refused: invalid block")
    assert client.get(_b(plan)).json()["blocks"] == []


@pytest.mark.parametrize("values", [
    json.dumps([{"s": "Energy", "w": 0.99}, {"s": "Utilities", "w": 0.31}]),
    "s,w\nEnergy,0.99\nUtilities,0.31",
    "s\tw\nEnergy\t0.99\nUtilities\t0.31",
])
def test_number_check_reads_chart_values_given_as_a_string(client, plan, tmp_path, values):
    chart = {"mark": "bar", "data": {"values": values, **({} if values.startswith("[") else
                                                           {"format": {"type": "tsv" if "\t" in values else "csv"}})},
             "encoding": {"x": {"field": "s", "type": "nominal"}, "y": {"field": "w", "type": "quantitative"}}}
    res = _draw(client, plan, tmp_path, {"kind": "chart", "title": "C", "source": chart})
    assert res.status_code == 200, res.text
    assert res.json()["unverified"] == [0.99]


def test_padded_prompt_is_sent_stripped(client, plan, tmp_path):
    _standin(tmp_path, {"output": {"kind": "note", "title": "S", "source": "s"}})
    res = client.post(f"{_b(plan)}/draw", json={"prompt": "  chart it" + " " * 50000})
    assert res.status_code == 200, res.text
    assert _calls(tmp_path)[0]["prompt"].startswith("Request: chart it\n\nThread data:\n")


INF_CHART = {"mark": "bar", "data": {"values": '[{"w": 1e999}, {"w": 0.77}]'},
             "encoding": {"y": {"field": "w", "type": "quantitative"}}}


def test_non_finite_string_values_are_not_numbers_on_draw(client, plan, tmp_path):
    res = _draw(client, plan, tmp_path, {"kind": "chart", "title": "C", "source": INF_CHART})
    assert res.status_code == 200, res.text
    assert res.json()["unverified"] == [0.77]


def test_non_finite_string_values_are_not_numbers_on_patch(client, plan):
    c = client.post(f"{_b(plan)}/blocks", json={"kind": "chart", "title": "C", "source": BAR_C}).json()
    res = client.patch(f"{_b(plan)}/blocks/{c['id']}", json={"source": INF_CHART})
    assert res.status_code == 200, res.text
    assert res.json()["unverified"] == [0.77]
