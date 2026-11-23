"""Agent board Phase 2 backend, slice 2b (spec docs/superpowers/specs/2026-11-22-agent-board.md, Amendment 1):
diagram, tiles and checklist checks, live pointers, D4 for tiles, and live drafts."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.agent_board import checks
from arp.agent_board.live import resolve, step_of
from arp.agent_board.store import BoardStore
from arp.api.routers import agent_board
from arp.orchestration.plan_store import PlanStore
from arp.standins import StandInLLMClient

SCRIPT = 'u = universe_build(taxonomy_id="t", source="u.csv")\n'
WEIGHTS = {"weights": [{"sector": "Energy", "weight": 0.125}, {"sector": "Utilities", "weight": 0.31}]}
MIND_M = "mindmap\n  root((Grow newsletter))\n    Topics\n    LinkedIn"
GROUPED_G = ("flowchart LR\n  a[Find flat]:::Housing --> b[Give notice]:::Berlin\n  b --> c[Register]:::Munich\n"
             "  class b emphasis")
W = "/steps/0/result/weights"
TYPES = "use flowchart, mindmap, timeline, sequenceDiagram or quadrantChart"


@pytest.fixture
def store(pg):
    return BoardStore(pg)


@pytest.fixture
def plans(pg):
    return PlanStore(pg)


@pytest.fixture
def plan(plans):
    """Done plan D."""
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


def _post(client, plan, kind, source, title="X", **extra):
    return client.post(f"{_b(plan)}/blocks", json={"kind": kind, "title": title, "source": source, **extra})


def _detail(res):
    assert res.status_code == 422, res.text
    return res.json()["detail"]


def _standin(folder, data):
    (folder / "model").mkdir(exist_ok=True)
    (folder / "model" / "BoardBlockDraft.json").write_text(json.dumps(data))


def _calls(folder):
    path = folder / "calls.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


# --- diagram (D6, D7) ---


def test_mind_map(client, plan):  # AC-33
    res = _post(client, plan, "diagram", MIND_M, title="M")
    assert res.status_code == 201, res.text
    b = res.json()
    assert (b["rendered"], b["live"], b["live_error"], b["live_step"]) == (None, False, None, None)
    assert client.get(_b(plan)).json()["blocks"][0]["source"] == MIND_M


def test_grouped_flowchart_is_accepted(client, plan):
    assert _post(client, plan, "diagram", GROUPED_G).status_code == 201


@pytest.mark.parametrize(("source", "detail"), [
    ("pie\n  \"a\": 1", f"unsupported diagram type: pie; {TYPES}"),  # AC-34
    ("%%{init: {\"theme\": \"dark\"}}%%\nflowchart LR\n  a --> b", "diagram may not set its own config"),  # AC-35
    ("flowchart LR\n  a --> b\n  click a call f()", "diagram may not use click lines"),  # AC-36
    ("flowchart LR\n  a[<img src=x onerror=f()>] --> b", "diagram may not contain HTML"),  # AC-36b
    ("flowchart LR\n" + "\n".join(f"  {c}[x]:::G{i}" for i, c in enumerate("abcde", 1)),
     "diagram has 5 colour groups; at most 4"),  # AC-36c
    ("flowchart LR\n  a[x] --> b[https://evil.test]", "diagram may not load from outside"),  # AC-36d
    ("x" * 8001, "diagram exceeds 8000 characters"),
    ("%% only a comment\n\n", f"unsupported diagram type: ; {TYPES}"),
    ("flowchart LR\n  style a fill:#f00", "diagram may not use style lines"),
    ("flowchart LR\n  classDef x fill:#f00", "diagram may not use classDef lines"),
    ("flowchart LR\n  linkStyle 0 stroke:red", "diagram may not use linkStyle lines"),
    ("flowchart LR\n  a --> b\n  class a big", "diagram may only use class lines for emphasis"),
    ("flowchart LR\n  a[JavaScript:x] --> b", "diagram may not load from outside"),
    ("flowchart LR\n  a[Start] --> b[End]; click a href \"x\" _blank", "diagram may not use click lines"),  # AC-36e
    ("sequenceDiagram\n  participant A as Analyst\n  link A: Report @ x\n  A->>A: Review",
     "diagram may not use link lines"),  # AC-36f
    ("sequenceDiagram\n  participant A\n  Links A: {}", "diagram may not use Links lines"),
    ("flowchart LR\n  a --> b;  HREF a x", "diagram may not use HREF lines"),
    ("flowchart LR\n  a --> b; class a big", "diagram may only use class lines for emphasis"),
    ("flowchart LR\n  a[see //evil.example] --> b", "diagram may not load from outside"),  # AC-36g
    ("flowchart LR\n  a[x:\\\\evil] --> b", "diagram may not load from outside"),  # AC-36h
    ("flowchart LR\n  a[x:\\evil] --> b", "diagram may not load from outside"),
    ("flowchart LR\n  a[\\\\host\\share] --> b", "diagram may not load from outside"),
    ("flowchart LR\n  a@{ img: \"x.png\" } --> b", "diagram may not use shape options"),  # AC-36i
    ("flowchart LR\n  a[http:evil.example] --> b", "diagram may not load from outside"),  # AC-36j
    ("sequenceDiagram\n  participant A as Analyst\n  properties A: {\"icon\": \"x.png\"}\n  A->>A: Review",
     "diagram may not use properties lines"),  # AC-36k
    ("flowchart LR\n  a[x\\/y] --> b", "diagram may not load from outside"),  # AC-36l
    ("sequenceDiagram\n  participant A as Analyst\n  details A: {\"x\": 1}\n  A->>A: Review",
     "diagram may not use details lines"),  # AC-36o
    ("sequenceDiagram\n  participant A as Analyst\n\ufeffproperties A: {\"icon\": \"x.png\"}\n  A->>A: Review",
     "diagram may not contain hidden characters"),  # AC-36r
    ("%%\u001cflowchart LR\nsequenceDiagram\n  A->>A: Review", "diagram may not contain hidden characters"),  # AC-36s
    ("flowchart LR\n  a --> b\u2028  click a x", "diagram may not contain hidden characters"),
    ("flowchart LR\n  a[see #47;#47;evil.example] --> b", "diagram may not use entity codes"),  # AC-36t
    ("flowchart LR\n  a --> b\r  click a href \"x\"", "diagram may not use click lines"),  # AC-36v
    ("flowchart LR\n  a --> b\n  click\u00a0a href \"x\"", "diagram may not use click lines"),  # AC-36w
    ("flowchart LR\n  subgraph s\n    a\n  end click a href \"x\"", "diagram may not use click lines"),  # AC-36z
    ("flowchart LR\n  a --> b\n  END end class a big", "diagram may only use class lines for emphasis"),
    ("\u3000flowchart\u2003LR\n  a --> b; style a x", "diagram may not use style lines"),
    ("flowchart LR\n  a --> b\n  accDescr { x } click a href \"x\"", "diagram may not use click lines"),  # AC-65
    ("flowchart LR\n  a[see \ufb02\u00b0\u00b047\u00b6\u00df] --> b", "diagram may not use entity codes"),  # AC-66
    ("flowchart LR\n  a[see \ufb02\u00b0\u00b047;] --> b", "diagram may not use entity codes"),  # AC-66b
    ("flowchart LR\n  a[x \u00b6\u00df] --> b", "diagram may not use entity codes"),
])
def test_diagram_checks(client, plan, source, detail):
    assert _detail(_post(client, plan, "diagram", source)) == detail
    assert client.get(_b(plan)).json()["blocks"] == []


@pytest.mark.parametrize("source", [
    "mindmap\r\n  root((Move))\r\n    Topics",  # AC-36x
    "mindmap\n  root((Team \U0001F9D1\u200d\U0001F4BB))\n    B\u00fcro",  # AC-36y
    "flowchart LR\n  a[Ends] --> b[end]",
    "flowchart LR\n  a --> b{Ready?}\n  b --> c[Stra\u00dfe]",  # AC-67
])
def test_diagrams_mermaid_reads_are_accepted(client, plan, source):
    res = _post(client, plan, "diagram", source)
    assert res.status_code == 201, res.text


def test_properties_and_details_only_refused_in_sequence_diagrams(client, plan):  # AC-36q
    assert _post(client, plan, "diagram", "mindmap\n  root((Move))\n    Details\n    Properties").status_code == 201


@pytest.mark.parametrize(("source", "detail"), [
    ("flowchart LR\n  a[<img src=x>] --> b", "diagram may not contain HTML"),  # AC-36m
    ("%%{init: {}}%%\nflowchart LR\n  a --> b", "diagram may not set its own config"),  # AC-36n
    ("flowchart LR\n  a[x //evil] --> b[y]", "diagram may not load from outside"),
    ("flowchart LR\n  a[\ufeffx] --> b", "diagram may not contain hidden characters"),
    ("flowchart LR\n  a[x #47;y] --> b", "diagram may not use entity codes"),
])
def test_flow_gets_diagram_checks(client, plan, source, detail):
    assert _detail(_post(client, plan, "flow", source)) == detail


def test_flow_decision_with_brace_and_eszett(client, plan):  # AC-67b
    res = _post(client, plan, "flow", "flowchart LR\n  a --> b{Ready?}\n  b --> c[Stra\u00dfe]")
    assert res.status_code == 201, res.text
    assert res.json()["rendered"]["steps"][1]["kind"] == "decision"


def test_flow_with_crlf_lines(client, plan):  # AC-36u
    src = "flowchart LR\n  a[Build universe] --> b[Extract]\r\n  b --> c[Report]"
    res = _post(client, plan, "flow", src)
    assert res.status_code == 201, res.text
    assert len(res.json()["rendered"]["steps"]) == 3


def test_flow_keeps_the_house_deck_subset(client, plan):  # AC-36p
    src = "flowchart LR\n  classDef Ops fill:#fff\n  a[Extract<br>Claude]:::Ops --> b:::Ops\n  class b stored"
    res = _post(client, plan, "flow", src)
    assert res.status_code == 201, res.text
    assert res.json()["rendered"]["steps"][0]["label"] == "Extract"


def test_diagram_source_not_a_string(client, plan):
    assert _detail(_post(client, plan, "diagram", {"a": 1})) == "invalid block"


def test_emphasis_is_not_a_group(client, plan):
    src = "flowchart LR\n" + "\n".join(f"  {c}[x]:::G{i}" for i, c in enumerate("abcd", 1)) + "\n  e:::emphasis"
    assert _post(client, plan, "diagram", src).status_code == 201


# --- tiles and checklist (D8) ---


def test_tiles_value_must_be_a_number(client, plan):  # AC-38
    assert _detail(_post(client, plan, "tiles", {"tiles": [{"label": "a", "value": "31%"}]})) == \
        "tile 1: value must be a number"


def test_five_tiles(client, plan):  # AC-38b
    assert _detail(_post(client, plan, "tiles", {"tiles": [{"label": "a", "value": 1}] * 5})) == \
        "tiles must have 1 to 4 tiles"


@pytest.mark.parametrize(("source", "detail"), [
    ({"tiles": []}, "tiles must have 1 to 4 tiles"),
    ({"tiles": [{"label": "  ", "value": 1}]}, "tile 1: label must be 1 to 40 characters"),
    ({"tiles": [{"label": "a", "value": 1}, {"label": "b", "value": True}]}, "tile 2: value must be a number"),
    ({"tiles": [{"label": "a", "value": 1, "change": "+3"}]}, "tile 1: change must be a number"),
    ({"tiles": [{"label": "a", "value": 1, "note": "n" * 81}]}, "tile 1: note exceeds 80 characters"),
    ({"tiles": [{"label": "a", "value": 1, "format": "money"}]}, "tile 1: format must be number or percent"),
    ({"tiles": [{"label": "a", "value": {"live": "steps"}}]}, "live must be a JSON Pointer starting with /"),
    ({"tiles": [{"label": "a", "value": 1, "colour": "red"}]}, "invalid block"),
    ({"tiles": [{"value": 1}]}, "invalid block"),
    ({"tiles": [1]}, "invalid block"),
    ({"tiles": {}}, "invalid block"),
    ({"tiles": [], "x": 1}, "invalid block"),
])
def test_tiles_checks(client, plan, source, detail):
    assert _detail(_post(client, plan, "tiles", source)) == detail


def test_tiles_rendered_values(client, plan):
    res = _post(client, plan, "tiles", {"tiles": [{"label": "a", "value": 0.31, "format": "percent", "change": 0.04,
                                                   "note": "vs Q2"}]})
    assert res.status_code == 201, res.text
    assert (res.json()["rendered"], res.json()["live"]) == ({"values": [0.31]}, False)


def test_checklist_tick_and_undo(client, plan):  # AC-39
    c = _post(client, plan, "checklist", {"items": [{"text": "Call vendor", "done": False}]}, title="C").json()["id"]
    res = client.patch(f"{_b(plan)}/blocks/{c}", json={"source": {"items": [{"text": "Call vendor", "done": True}]}})
    b = res.json()
    assert (b["version"], b["origin"], b["source"]["items"][0]["done"], b["rendered"]) == (2, "person", True, None)
    b = client.post(f"{_b(plan)}/blocks/{c}/undo").json()
    assert (b["version"], b["source"]["items"][0]["done"]) == (3, False)


@pytest.mark.parametrize(("source", "detail"), [
    ({"items": []}, "checklist must have 1 to 50 items"),  # AC-40
    ({"items": [{"text": "a", "done": False}] * 51}, "checklist must have 1 to 50 items"),
    ({"items": [{"text": " ", "done": False}]}, "item 1: text must be 1 to 200 characters"),
    ({"items": [{"text": "a", "done": False}, {"text": "b", "done": "yes"}]}, "item 2: done must be true or false"),
    ({"items": [{"text": "a"}]}, "item 1: done must be true or false"),
    ({"items": [{"done": False}]}, "invalid block"),
    ({"items": [{"text": "a", "done": False, "due": "x"}]}, "invalid block"),
    ([], "invalid block"),
])
def test_checklist_checks(client, plan, source, detail):
    assert _detail(_post(client, plan, "checklist", source)) == detail


def test_unverified_always_empty_for_checklist_and_diagram(client, plan):  # AC-62
    a = _post(client, plan, "checklist", {"items": [{"text": "a", "done": False}]}, unverified=[1])
    b = _post(client, plan, "diagram", MIND_M, unverified=[1])
    assert [(r.status_code, r.json()["unverified"]) for r in (a, b)] == [(201, []), (201, [])]


def test_number_check_on_a_persons_tiles_edit(client, plan):  # AC-59
    t = _post(client, plan, "tiles", {"tiles": [{"label": "a", "value": 0.31}]}, title="T").json()
    assert t["unverified"] == []
    res = client.patch(f"{_b(plan)}/blocks/{t['id']}", json={"source": {"tiles": [{"label": "a", "value": 9.99}]}})
    assert res.json()["unverified"] == [9.99]


# --- live pointers (D9) ---


def test_live_table(client, plan):  # AC-41
    src = {"live": W, "columns": ["sector", "weight"]}
    res = _post(client, plan, "table", src, title="W")
    assert res.status_code == 201, res.text
    b = res.json()
    assert (b["live"], b["live_error"], b["unverified"], b["live_step"]) == (True, None, [], 1)
    assert b["rendered"] == {"rows": [["Energy", 0.125], ["Utilities", 0.31]]}
    assert b["source"] == src


def test_live_table_follows_the_data(client, plan, plans):  # AC-42
    _post(client, plan, "table", {"live": W, "columns": ["sector", "weight"]})
    plans.update_call(plan, 1, result={"weights": [{"sector": "Energy", "weight": 0.125},
                                                   {"sector": "Utilities", "weight": 0.4}]})
    [b] = client.get(_b(plan)).json()["blocks"]
    assert (b["rendered"]["rows"], b["version"]) == ([["Energy", 0.125], ["Utilities", 0.4]], 1)


def test_live_pointer_not_found(client, plan):  # AC-43
    res = _post(client, plan, "table", {"live": "/steps/5/result", "columns": ["a"]})
    assert res.status_code == 201
    b = res.json()
    assert (b["live_error"], b["rendered"], b["live_step"]) == ("live data not found: /steps/5/result", {"rows": []},
                                                                None)


def test_live_pointer_form(client, plan):  # AC-43b
    assert _detail(_post(client, plan, "table", {"live": "steps/0", "columns": ["a"]})) == \
        "live must be a JSON Pointer starting with /"


@pytest.mark.parametrize("source", [
    {"live": W, "columns": ["sector"], "rows": []},  # AC-60
    {"columns": ["sector"]},
    {"live": W, "columns": [1]},
])
def test_live_table_shape(client, plan, source):
    assert _detail(_post(client, plan, "table", source)) == "invalid block"


def test_live_table_columns_check(client, plan):
    assert _detail(_post(client, plan, "table", {"live": W, "columns": []})) == "table must have 1 to 20 columns"


def test_live_table_rows_not_objects(client, plan):
    b = _post(client, plan, "table", {"live": "/steps/0/result", "columns": ["a"]}).json()
    assert (b["live_error"], b["rendered"]) == ("live data is not a list of rows: /steps/0/result", {"rows": []})


def test_live_table_cells_and_row_limit(client, plan, plans):
    rows = [{"a": i, "b": {"x": [1]}, "c": True} for i in range(201)]
    plans.update_call(plan, 1, result={"rows": rows})
    b = _post(client, plan, "table", {"live": "/steps/0/result/rows", "columns": ["a", "b", "c", "d"]}).json()
    assert b["live_error"] == "live data exceeds 200 rows"
    assert len(b["rendered"]["rows"]) == 200
    assert b["rendered"]["rows"][0] == [0, '{"x":[1]}', "true", None]


def test_live_chart(client, plan):  # AC-44
    src = {"live": W, "mark": "bar", "encoding": {"x": {"field": "sector", "type": "nominal"},
                                                  "y": {"field": "weight", "type": "quantitative"}}}
    res = _post(client, plan, "chart", src, title="C")
    assert res.status_code == 201, res.text
    b = res.json()
    assert (b["live"], b["live_error"], b["unverified"], b["live_step"]) == (True, None, [], 1)
    assert "#2a78d6" in b["rendered"]["light"] and "Utilities" in b["rendered"]["light"]
    assert b["source"] == src


def test_live_chart_image_mark(client, plan):  # AC-45
    src = {"live": W, "mark": "image", "encoding": {"url": {"field": "sector"}}}
    assert _detail(_post(client, plan, "chart", src)) == "chart may not load from outside: mark"


def test_live_chart_with_data_is_invalid(client, plan):
    src = {"live": W, "data": {"values": []}, "mark": "bar"}
    assert _detail(_post(client, plan, "chart", src)) == "invalid block"


def test_live_chart_pointer_form(client, plan):
    assert _detail(_post(client, plan, "chart", {"live": "", "mark": "bar"})) == \
        "live must be a JSON Pointer starting with /"


def test_live_chart_too_many_rows(client, plan, plans):  # AC-58
    plans.update_call(plan, 1, result={"rows": [{"v": 1}] * 5001})
    src = {"live": "/steps/0/result/rows", "mark": "point", "encoding": {"y": {"field": "v", "type": "quantitative"}}}
    res = _post(client, plan, "chart", src)
    assert res.status_code == 201
    assert (res.json()["rendered"], res.json()["live_error"]) == (None, "chart exceeds 5000 data rows")


def test_live_chart_not_found_draws_empty(client, plan):
    b = _post(client, plan, "chart", {"live": "/nope", "mark": "bar"}).json()
    assert b["live_error"] == "live data not found: /nope"
    assert b["rendered"]["light"].startswith("<svg")


def test_live_tiles(client, plan):  # AC-46
    src = {"tiles": [{"label": "Utilities", "value": {"live": "/steps/0/result/weights/1/weight"}},
                     {"label": "Bad", "value": {"live": "/steps/0/result/weights/1/sector"}}]}
    res = _post(client, plan, "tiles", src)
    assert res.status_code == 201, res.text
    b = res.json()
    assert b["rendered"] == {"values": [0.31, None]}
    assert b["live_error"] == "live data is not a number: /steps/0/result/weights/1/sector"
    assert (b["live"], b["live_step"], b["unverified"]) == (True, 1, [])


def test_non_live_blocks_answer_live_false(client, plan):
    _post(client, plan, "note", "a")
    [b] = client.get(_b(plan)).json()["blocks"]
    assert (b["live"], b["live_error"], b["live_step"]) == (False, None, None)


def test_pointer_resolution():
    data = {"a/b": {"~": [10, 20]}, "steps": [{"seq": 7}]}
    assert resolve("/a~1b/~0/1", data) == 20
    assert resolve("/a~1b/~0/01", data) != 20  # leading zeros are not an index
    assert step_of("/steps/0/result", data) == 7
    assert step_of("/steps/1", data) is None
    assert step_of("/brief", data) is None


# --- drawing ---


def test_draw_tiles(client, plan, tmp_path):  # AC-37
    _standin(tmp_path, {"output": {"kind": "tiles", "title": "Key", "source": {"tiles": [
        {"label": "Utilities", "value": 0.31, "format": "percent"}, {"label": "Other", "value": 0.5}]}}})
    res = client.post(f"{_b(plan)}/draw", json={"prompt": "key numbers"})
    assert res.status_code == 200, res.text
    b = res.json()
    assert (b["kind"], b["unverified"], b["rendered"]) == ("tiles", [0.5], {"values": [0.31, 0.5]})


def test_draw_diagram(client, plan, tmp_path):
    _standin(tmp_path, {"output": {"kind": "diagram", "title": "M", "source": MIND_M}})
    res = client.post(f"{_b(plan)}/draw", json={"prompt": "mind map"})
    assert (res.status_code, res.json()["kind"], res.json()["origin"]) == (200, "diagram", "agent")


def test_draw_with_live_error_is_refused_then_retried(client, plan, tmp_path):
    bad = {"kind": "table", "title": "W", "source": {"live": "/steps/9", "columns": ["a"]}}
    good = {"kind": "table", "title": "W", "source": {"live": W, "columns": ["sector", "weight"]}}
    _standin(tmp_path, [{"output": bad}, {"output": good}])
    res = client.post(f"{_b(plan)}/draw", json={"prompt": "table"})
    assert res.status_code == 200, res.text
    assert (res.json()["live"], res.json()["live_error"]) == (True, None)
    calls = _calls(tmp_path)
    assert calls[-1]["prompt"].endswith("Your last answer was refused: live data not found: /steps/9")


def test_draw_with_two_live_errors(client, plan, tmp_path):
    bad = {"kind": "table", "title": "W", "source": {"live": "/steps/9", "columns": ["a"]}}
    _standin(tmp_path, [{"output": bad}])
    res = client.post(f"{_b(plan)}/draw", json={"prompt": "table"})
    assert (res.status_code, res.json()) == (422, {"detail": "the agent could not draw this: live data not found: "
                                                             "/steps/9"})
    assert client.get(_b(plan)).json()["blocks"] == []


# --- Amendment 1b ---


def _failing_render(calls):
    def render(source):
        calls.append(source)
        raise checks.RenderFailed("boom")
    return render


LIVE_BAR = {"live": W, "mark": "bar", "encoding": {"x": {"field": "sector", "type": "nominal"},
                                                   "y": {"field": "weight", "type": "quantitative"}}}


def test_live_chart_that_does_not_render_is_refused(client, plan, monkeypatch):  # AC-58b
    monkeypatch.setattr(checks, "render_chart", _failing_render([]))
    assert _detail(_post(client, plan, "chart", LIVE_BAR)) == "chart does not render: boom"
    assert client.get(_b(plan)).json()["blocks"] == []


def test_failed_live_render_is_remembered(client, plan, plans, monkeypatch):  # AC-58d
    assert _post(client, plan, "chart", LIVE_BAR).status_code == 201
    calls = []
    monkeypatch.setattr(checks, "render_chart", _failing_render(calls))
    first = client.get(_b(plan)).json()["blocks"][0]
    second = client.get(_b(plan)).json()["blocks"][0]
    assert first["live_error"] == second["live_error"] == "chart does not render: boom"
    assert (first["rendered"], len(calls)) == (None, 1)
    plans.update_call(plan, 1, result={"weights": [{"sector": "Energy", "weight": 0.2}]})
    client.get(_b(plan))
    assert len(calls) == 2  # new data: rendered again


def test_failed_render_memory_is_bounded(monkeypatch):
    monkeypatch.setattr(checks, "render_chart", _failing_render([]))
    monkeypatch.setattr(checks, "_FAILED_RENDERS", type(checks._FAILED_RENDERS)())
    for i in range(checks.MAX_FAILED_RENDERS + 5):
        checks.view("chart", {"live": "/x", "mark": "bar"}, {"x": []}, (f"b{i}", 1))
    assert len(checks._FAILED_RENDERS) == checks.MAX_FAILED_RENDERS
    assert next(iter(checks._FAILED_RENDERS))[0] == "b5"


def test_long_live_cells_are_cut(client, plan, plans):  # AC-58c
    plans.update_call(plan, 1, result={"rows": [{"note": "x" * 2000, "obj": {"k": "y" * 2000}, "n": 1.5}]})
    _post(client, plan, "table", {"live": "/steps/0/result/rows", "columns": ["note", "obj", "n"]})
    [row] = client.get(_b(plan)).json()["blocks"][0]["rendered"]["rows"]
    assert row[0] == "x" * 1000 + "…"
    assert row[1] == ('{"k":"' + "y" * 2000)[:1000] + "…"
    assert row[2] == 1.5
