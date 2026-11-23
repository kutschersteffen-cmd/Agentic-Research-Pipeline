"""POST /api/agent/explorations/{id}/miniapp (spec agent-panel-code-mode, Phase 5, slice 11, D14)."""
from __future__ import annotations

import asyncio
import json

from arp.agent.explorations import ExplorationStore, MiniApp, write_miniapp
from arp.agent.miniapp_html import clean_miniapp_html
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
    return TestClient(app, raise_server_exceptions=False)


def _stand_in(folder, question, html, asks):
    (folder / "miniapp.json").write_text(json.dumps({question: {"html": html, "asks": asks}}))


def _calls(folder):
    path = folder / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_done_exploration_stores_the_page_and_its_asks(pg, tmp_path):  # AC-54's backend half
    store = ExplorationStore(pg)
    e = store.add(question="weights?", code="return 1", run=RUN, model="stand-in")
    assert (e["miniapp_html"], e["miniapp_asks"]) == (None, None)
    _stand_in(tmp_path, "weights?", "<p>hi</p>", ["why IT?"])
    client = _client(pg, tmp_path)
    res = client.post(f"/api/agent/explorations/{e['id']}/miniapp")
    assert res.status_code == 200
    assert (res.json()["miniapp_html"], res.json()["miniapp_asks"]) == ("<p>hi</p>", ["why IT?"])
    got = client.get(f"/api/agent/explorations/{e['id']}").json()
    assert (got["miniapp_html"], got["miniapp_asks"]) == ("<p>hi</p>", ["why IT?"])
    assert _calls(tmp_path) == [{"kind": "model", "name": "MiniApp", "question": "weights?"}]


def test_asks_drop_blanks_keep_five_and_cut_each_to_200(pg, tmp_path):  # AC-54e
    e = ExplorationStore(pg).add(question="q54e", code="x", run=RUN, model=None)
    long = "L" * 250
    _stand_in(tmp_path, "q54e", "<p>x</p>", ["", "  ", "a", "b", long, "c", "d", "e"])
    res = _client(pg, tmp_path).post(f"/api/agent/explorations/{e['id']}/miniapp")
    assert (res.status_code, res.json()["miniapp_asks"]) == (200, ["a", "b", long[:200], "c", "d"])


def test_stored_html_keeps_allowed_markup_and_loses_every_way_out(pg, tmp_path):  # AC-54f, AC-54g, AC-54h
    e = ExplorationStore(pg).add(question="q54f", code="x", run=RUN, model=None)
    _stand_in(tmp_path, "q54f", '<base href="http://x/"><meta http-equiv="refresh" content="0;url=http://x/">'
              '<a href="http://x/" onclick="f()">go</a><svg><a xlink:href="http://x/"><text>s</text></a></svg>'
              '<form action="http://x/"><button formaction="http://x/">b</button></form><SCRIPT>f()</SCRIPT>'
              '<p class="k">ok</p><svg><a><set attributeName="href" to="http://127.0.0.1:9/x"/><text>go</text></a>'
              '<use href="#z"/><animate attributeName="x"/></svg>', [])
    html = _client(pg, tmp_path).post(f"/api/agent/explorations/{e['id']}/miniapp").json()["miniapp_html"]
    assert '<p class="k">ok</p>' in html
    for gone in ("<script", "f()", "<base", "<meta", "<a", "<form", "<button", "onclick", "href", "action=", "<set",
                 "<use", "<animate"):
        assert gone not in html.lower(), gone


def test_cleaning_keeps_the_allowlist_and_nothing_else():
    assert clean_miniapp_html(
        '<!-- c --><table class="t" onclick="x"><tr><td colspan="2" style="color:red">1 &lt;b&gt;</td></tr></table>'
        '<details open><summary>s</summary><img src="data:x"><iframe srcdoc="<p>"></iframe></details>'
        '<svg viewBox="0 0 1 1" onload="x"><rect width="1" fill="red" href="#a"/></svg>') == (
        '<table class="t"><tr><td colspan="2" style="color:red">1 &lt;b&gt;</td></tr></table>'
        '<details open><summary>s</summary></details><svg viewbox="0 0 1 1"><rect fill="red" width="1"></rect></svg>')
    # Inside <svg> a browser parses <style> as markup: no '<' is left in any style text.
    assert clean_miniapp_html("<svg><style><a href=x>go</a></style></svg>") == "<svg><style>\\3C a href=x>go\\3C /a></style></svg>"


def test_each_post_writes_again(pg, tmp_path):  # AC-54i
    store = ExplorationStore(pg)
    e = store.add(question="q54i", code="x", run=RUN, model=None)
    client = _client(pg, tmp_path)
    _stand_in(tmp_path, "q54i", "<p>x</p>", [])
    assert client.post(f"/api/agent/explorations/{e['id']}/miniapp").status_code == 200
    _stand_in(tmp_path, "q54i", "<p>y</p>", ["again?"])
    assert client.post(f"/api/agent/explorations/{e['id']}/miniapp").status_code == 200
    assert _calls(tmp_path) == [{"kind": "model", "name": "MiniApp", "question": "q54i"}] * 2
    got = store.get(e["id"])
    assert (got["miniapp_html"], got["miniapp_asks"]) == ("<p>y</p>", ["again?"])


def test_not_done_is_409_and_missing_is_404(pg, tmp_path):  # AC-54b
    store = ExplorationStore(pg)
    client = _client(pg, tmp_path)
    for status in ("failed", "timeout"):
        e = store.add(question="q", code="x", run={**RUN, "status": status, "result": None, "error": "e"}, model=None)
        res = client.post(f"/api/agent/explorations/{e['id']}/miniapp")
        assert (res.status_code, res.json()) == (409, {"detail": "only a done exploration can be shown as a mini-app"})
        assert store.get(e["id"])["miniapp_html"] is None
    assert _calls(tmp_path) == []  # no model call for either
    for missing in ("00000000-0000-0000-0000-000000000000", "abc"):
        res = client.post(f"/api/agent/explorations/{missing}/miniapp")
        assert (res.status_code, res.json()) == (404, {"detail": "exploration not found"})


def test_a_missing_or_malformed_stand_in_is_500(pg, tmp_path):
    e = ExplorationStore(pg).add(question="none", code="return 1", run=RUN, model=None)
    client = _client(pg, tmp_path)
    for entry in (None, {"html": "<p>x</p>"}, {"asks": []}, {"html": 1, "asks": []}, {"html": "x", "asks": [1]}):
        (tmp_path / "miniapp.json").write_text(json.dumps({"none": entry} if entry else {}))
        res = client.post(f"/api/agent/explorations/{e['id']}/miniapp")
        assert (res.status_code, res.json()) == (500, {"detail": "no stand-in mini-app for none in miniapp.json"}), entry


def test_real_model_gets_the_question_and_the_result_and_is_cleaned(pg, fake_llm):
    store = ExplorationStore(pg)
    e = store.add(question="weights?", code="return 1", run=RUN, model=None)
    llm = fake_llm({"MiniApp": [MiniApp(html="<h1 onclick='x'>w</h1><script>x</script>", asks=["", "why?"])]})
    row = asyncio.run(write_miniapp(store, Settings(standins_dir=None), e["id"], llm=llm))
    assert (row["miniapp_html"], row["miniapp_asks"]) == ("<h1>w</h1>", ["why?"])
    [prompt] = llm.prompts
    assert prompt.startswith("Question: weights?")
    assert '"sector": "IT"' in prompt
