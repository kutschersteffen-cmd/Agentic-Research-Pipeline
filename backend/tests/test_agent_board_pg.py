"""Agent board API, slice 1 (spec docs/superpowers/specs/2026-11-22-agent-board.md, AC-1 to AC-13e)."""
from __future__ import annotations

import socket

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from arp.agent_board.store import BoardStore
from arp.api.routers import agent_board
from arp.orchestration.plan_store import PlanStore

SCRIPT = 'u = universe_build(taxonomy_id="t", source="u.csv")\n'
BAR_C = {"mark": "bar", "data": {"values": [{"s": "Energy", "w": 0.125}, {"s": "Utilities", "w": 0.31}]},
         "encoding": {"x": {"field": "s", "type": "nominal"}, "y": {"field": "w", "type": "quantitative"}}}
FLOW_F = "flowchart LR\n  a[Build universe] --> b[Extract]\n  b --> c[Report]"


@pytest.fixture
def store(pg):
    return BoardStore(pg)


@pytest.fixture
def plan(pg):
    return PlanStore(pg).create("b", SCRIPT)


@pytest.fixture
def client(store):
    app = FastAPI()
    app.include_router(agent_board.router)
    app.dependency_overrides[agent_board.board_store] = lambda: store
    with TestClient(app) as c:
        yield c


def _b(plan):
    return f"/api/agent/boards/plan/{plan}"


def _note(client, plan, title, source="a"):
    res = client.post(f"{_b(plan)}/blocks", json={"kind": "note", "title": title, "source": source})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _titles(client, plan):
    return [(b["title"], b["position"]) for b in client.get(_b(plan)).json()["blocks"]]


@pytest.fixture
def listener():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    srv.settimeout(2)
    yield srv
    srv.close()


def _no_connection(srv):
    with pytest.raises(TimeoutError):
        srv.accept()


def test_empty_board(client, plan):  # AC-1
    res = client.get(_b(plan))
    assert res.status_code == 200
    assert res.json() == {"thread_kind": "plan", "thread_id": plan, "blocks": []}


def test_unknown_thread_and_kind(client, pg):  # AC-2, AC-2b
    assert client.get("/api/agent/boards/plan/nope").json() == {"detail": "thread not found"}
    res = client.get("/api/agent/boards/folder/x")
    assert (res.status_code, res.json()) == (404, {"detail": "unknown thread kind"})
    assert client.get("/api/agent/boards/exploration/x").json() == {"detail": "unknown thread kind"}


def test_create_note(client, plan):  # AC-3
    res = client.post(f"{_b(plan)}/blocks", json={"kind": "note", "title": "Why", "source": "Because **x**"})
    assert res.status_code == 201
    b = res.json()
    assert (b["position"], b["version"], b["origin"], b["unverified"], b["rendered"]) == (0, 1, "person", [], None)
    assert client.get(_b(plan)).json()["blocks"] == [b]


@pytest.mark.parametrize(("body", "detail"), [
    ({"kind": "table", "title": "T", "source": {"columns": ["a", "b"], "rows": [[1, 2], [3]]}},
     "row 2 has 1 cells, expected 2"),  # AC-4
    ({"kind": 3, "title": "x", "source": ""}, "invalid block"),  # AC-4b
    ({"kind": "note", "title": "x" * 121, "source": ""}, "title must be 1 to 120 characters"),  # AC-5
    ({"kind": "note", "title": "   ", "source": ""}, "title must be 1 to 120 characters"),
    ({"kind": "pie", "title": "x", "source": ""}, "unknown block kind: pie"),
    ({"kind": "note", "title": "x", "source": "y" * 20001}, "note exceeds 20000 characters"),
    ({"kind": "table", "title": "T", "source": {"columns": [], "rows": []}}, "table must have 1 to 20 columns"),
    ({"kind": "table", "title": "T", "source": {"columns": ["a"], "rows": [[1]] * 201}}, "table exceeds 200 rows"),
    ({"kind": "chart", "title": "C", "source": {"layer": [{"mark": {"type": "image"},
                                                            "encoding": {"url": {"value": "https://example.com/a.png"}}}]}},
     "chart may not load from outside: layer[0].mark"),  # AC-8
    ({"kind": "chart", "title": "C", "source": {"mark": {"type": "point", "href": "x"}}},
     "chart may not load from outside: mark.href"),
    ({"kind": "chart", "title": "C", "source": {"mark": "bar", "data": {"values": [{"a": 1}] * 5001}}},
     "chart exceeds 5000 data rows"),
    ({"kind": "flow", "title": "F", "source": "flowchart RL\n  a --> b"},
     "line 1: direction RL is not supported; use LR or TB"),  # AC-10
])
def test_create_refused(client, plan, body, detail):
    res = client.post(f"{_b(plan)}/blocks", json=body)
    assert (res.status_code, res.json()) == (422, {"detail": detail})
    assert client.get(_b(plan)).json()["blocks"] == []


def test_body_not_an_object(client, plan):  # AC-4b
    for content in (b"[1]", b"not json"):
        res = client.post(f"{_b(plan)}/blocks", content=content, headers={"content-type": "application/json"})
        assert (res.status_code, res.json()) == (422, {"detail": "invalid block"})


def test_chart_renders_house_theme(client, plan):  # AC-6
    res = client.post(f"{_b(plan)}/blocks", json={"kind": "chart", "title": "C", "source": BAR_C})
    assert res.status_code == 201
    r = res.json()["rendered"]
    assert r["light"].startswith("<svg") and r["dark"].startswith("<svg")
    assert "#2a78d6" in r["light"]
    assert "#3987e5" in r["dark"] and "#e8ebf0" in r["dark"]
    assert res.json()["source"] == BAR_C


def test_chart_url_refused_without_fetching(client, plan, listener):  # AC-7
    p = listener.getsockname()[1]
    res = client.post(f"{_b(plan)}/blocks", json={"kind": "chart", "title": "C",
                                                  "source": {"mark": "bar", "data": {"url": f"http://127.0.0.1:{p}/x.csv"}}})
    assert (res.status_code, res.json()) == (422, {"detail": "chart may not load from outside: data.url"})
    _no_connection(listener)


def test_image_mark_refused_without_fetching(client, plan, listener):  # AC-8b
    p = listener.getsockname()[1]
    src = {"mark": "image", "data": {"values": [{"u": f"http://127.0.0.1:{p}/a.png"}]}, "encoding": {"url": {"field": "u"}}}
    res = client.post(f"{_b(plan)}/blocks", json={"kind": "chart", "title": "C", "source": src})
    assert (res.status_code, res.json()) == (422, {"detail": "chart may not load from outside: mark"})
    _no_connection(listener)


def test_chart_that_does_not_render(client, plan):
    res = client.post(f"{_b(plan)}/blocks", json={"kind": "chart", "title": "C", "source": {"mark": "nope"}})
    assert res.status_code == 422
    assert res.json()["detail"].startswith("chart does not render: ")


def test_flow(client, plan):  # AC-9
    res = client.post(f"{_b(plan)}/blocks", json={"kind": "flow", "title": "F", "source": FLOW_F})
    assert res.status_code == 201
    r = res.json()["rendered"]
    assert [s["label"] for s in r["steps"]] == ["Build universe", "Extract", "Report"]
    assert r["direction"] == "LR"


def test_board_full(client, plan):  # AC-11
    for i in range(50):
        _note(client, plan, f"n{i}")
    res = client.post(f"{_b(plan)}/blocks", json={"kind": "note", "title": "x", "source": "y"})
    assert (res.status_code, res.json()) == (409, {"detail": "board is full (50 blocks)"})


def test_move(client, plan):  # AC-12
    ids = [_note(client, plan, f"N{i}") for i in range(3)]
    res = client.patch(f"{_b(plan)}/blocks/{ids[2]}", json={"position": 0})
    assert res.status_code == 200
    blocks = client.get(_b(plan)).json()["blocks"]
    assert [(b["title"], b["position"], b["version"]) for b in blocks] == [("N2", 0, 1), ("N0", 1, 1), ("N1", 2, 1)]
    client.patch(f"{_b(plan)}/blocks/{ids[2]}", json={"position": 2})
    assert _titles(client, plan) == [("N0", 0), ("N1", 1), ("N2", 2)]


def test_move_clamped(client, plan):  # AC-12b
    n0 = _note(client, plan, "N0")
    _note(client, plan, "N1")
    client.patch(f"{_b(plan)}/blocks/{n0}", json={"position": 99})
    assert _titles(client, plan) == [("N1", 0), ("N0", 1)]


def test_insert_at_position(client, plan):
    _note(client, plan, "N0")
    _note(client, plan, "N1")
    res = client.post(f"{_b(plan)}/blocks", json={"kind": "note", "title": "X", "source": "", "position": 1,
                                                  "origin": "agent", "unverified": [0.5]})
    assert (res.json()["origin"], res.json()["unverified"]) == ("agent", [0.5])
    assert _titles(client, plan) == [("N0", 0), ("X", 1), ("N1", 2)]


def test_edit_and_undo(client, plan):  # AC-13, AC-13b, AC-13e
    n = _note(client, plan, "N", "a")
    res = client.post(f"{_b(plan)}/blocks/{n}/undo")
    assert (res.status_code, res.json()) == (409, {"detail": "nothing to undo"})
    b = client.patch(f"{_b(plan)}/blocks/{n}", json={"source": "b"}).json()
    assert (b["version"], b["source"]) == (2, "b")
    u = client.post(f"{_b(plan)}/blocks/{n}/undo")
    assert u.status_code == 200
    assert (u.json()["version"], u.json()["source"]) == (3, "a")
    u = client.post(f"{_b(plan)}/blocks/{n}/undo").json()
    assert (u["version"], u["source"]) == (4, "b")


def test_title_edit_keeps_origin(client, plan):
    res = client.post(f"{_b(plan)}/blocks", json={"kind": "note", "title": "N", "source": "a", "origin": "agent"})
    b = client.patch(f"{_b(plan)}/blocks/{res.json()['id']}", json={"title": "M"}).json()
    assert (b["version"], b["title"], b["origin"]) == (2, "M", "agent")
    b = client.patch(f"{_b(plan)}/blocks/{b['id']}", json={"source": "c"}).json()
    assert (b["version"], b["origin"]) == (3, "person")


def test_patch_refused(client, plan):
    n = _note(client, plan, "N")
    res = client.patch(f"{_b(plan)}/blocks/{n}", json={"title": ""})
    assert (res.status_code, res.json()) == (422, {"detail": "title must be 1 to 120 characters"})
    res = client.patch(f"{_b(plan)}/blocks/{n}", json={"source": 3})
    assert (res.status_code, res.json()) == (422, {"detail": "invalid block"})


def test_delete(client, plan, pg, store):  # AC-13c
    ids = [_note(client, plan, f"N{i}") for i in range(3)]
    client.patch(f"{_b(plan)}/blocks/{ids[1]}", json={"source": "z"})
    res = client.delete(f"{_b(plan)}/blocks/{ids[1]}")
    assert res.status_code == 204
    assert _titles(client, plan) == [("N0", 0), ("N2", 1)]
    with store.engine.connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM agent_board_versions WHERE block_id = :b"), {"b": ids[1]}).scalar()
    assert n == 0


def test_block_on_another_board(client, plan, pg):  # AC-13d
    other = PlanStore(pg).create("other", SCRIPT)
    x = _note(client, other, "X")
    for res in (client.patch(f"{_b(plan)}/blocks/{x}", json={"title": "y"}),
                client.post(f"{_b(plan)}/blocks/{x}/undo"), client.delete(f"{_b(plan)}/blocks/{x}")):
        assert (res.status_code, res.json()) == (404, {"detail": "block not found"})
    assert _titles(client, other) == [("X", 0)]
