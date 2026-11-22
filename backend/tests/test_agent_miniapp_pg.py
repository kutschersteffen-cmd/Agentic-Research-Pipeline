"""POST /api/agent/explorations/{id}/miniapp (spec agent-panel-code-mode, Phase 5, slice 11)."""
from __future__ import annotations

import asyncio
import json

from arp.agent.explorations import ExplorationStore, MiniApp, write_miniapp
from arp.config import Settings

RUN = {"status": "done", "result": [{"sector": "IT", "weight": 0.25}], "error": None, "tool_calls": []}


def _client(pg, standins):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from arp.api.auth import Principal, current_user
    from arp.api.deps import settings_dep
    from arp.api.routers import agent

    app = FastAPI()
    app.include_router(agent.router)
    app.dependency_overrides[agent.exploration_store] = lambda: ExplorationStore(pg)
    app.dependency_overrides[settings_dep] = lambda: Settings(standins_dir=standins, anthropic_api_key=None, gemini_api_key=None)
    app.dependency_overrides[current_user] = lambda: Principal(user_id="alice", name="alice", role="analyst")
    return TestClient(app)


def test_done_exploration_stores_the_stand_in_html(pg, tmp_path):  # AC-54's backend half
    store = ExplorationStore(pg)
    e = store.add(question="weights?", code="return 1", run=RUN, model="stand-in")
    assert e["miniapp_html"] is None
    (tmp_path / "miniapp.json").write_text(json.dumps({"weights?": {"html": "<p>hi</p>"}}))
    client = _client(pg, tmp_path)
    res = client.post(f"/api/agent/explorations/{e['id']}/miniapp")
    assert res.status_code == 200
    assert res.json()["miniapp_html"] == "<p>hi</p>"
    assert client.get(f"/api/agent/explorations/{e['id']}").json()["miniapp_html"] == "<p>hi</p>"
    logged = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert logged == [{"kind": "model", "name": "MiniApp", "question": "weights?"}]


def test_not_done_is_409_and_missing_is_404(pg, tmp_path):  # AC-54b
    store = ExplorationStore(pg)
    client = _client(pg, tmp_path)
    for status in ("failed", "timeout"):
        e = store.add(question="q", code="x", run={**RUN, "status": status, "result": None, "error": "e"}, model=None)
        res = client.post(f"/api/agent/explorations/{e['id']}/miniapp")
        assert (res.status_code, res.json()) == (409, {"detail": "only a done exploration can be shown as a mini-app"})
        assert store.get(e["id"])["miniapp_html"] is None
    assert not (tmp_path / "calls.jsonl").exists()  # no model call for either
    for missing in ("00000000-0000-0000-0000-000000000000", "abc"):
        res = client.post(f"/api/agent/explorations/{missing}/miniapp")
        assert (res.status_code, res.json()) == (404, {"detail": "exploration not found"})


def test_no_stand_in_html_is_502(pg, tmp_path):
    e = ExplorationStore(pg).add(question="none", code="return 1", run=RUN, model=None)
    res = _client(pg, tmp_path).post(f"/api/agent/explorations/{e['id']}/miniapp")
    assert res.status_code == 502
    assert "no stand-in mini-app for 'none'" in res.json()["detail"]


def test_real_model_gets_the_question_and_the_result(pg, fake_llm):
    store = ExplorationStore(pg)
    e = store.add(question="weights?", code="return 1", run=RUN, model=None)
    llm = fake_llm({"MiniApp": [MiniApp(html="<h1>w</h1>")]})
    row = asyncio.run(write_miniapp(store, Settings(standins_dir=None), e["id"], llm=llm))
    assert row["miniapp_html"] == "<h1>w</h1>"
    [prompt] = llm.prompts
    assert prompt.startswith("Question: weights?")
    assert '"sector": "IT"' in prompt
