"""Research Desk slice 1, the unit rows of spec research-desk-wave1 (AC-17, AC-29, AC-30, AC-31, AC-85), over HTTP
with the stand-in model."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.main import app
from arp.config import get_settings
from arp.db import models as m
from arp.db.session import transaction

ALICE = Principal(user_id="alice", name="alice", role="analyst")
GROUP = "Group capex: EUR 3,100 million."
ANSWER = {"output": {"sentences": [{"text": "Group capex was EUR 3,100 million.",
                                    "citations": [{"source": 1, "quote": GROUP}]}]}}


class Env:
    def __init__(self, client, folder):
        self.client, self.folder = client, folder

    def answer(self, entry=ANSWER):
        (self.folder / "model" / "DeskAnswer.json").write_text(json.dumps(entry))

    def model_calls(self, name):
        path = self.folder / "calls.jsonl"
        return [c for c in map(json.loads, path.read_text().splitlines()) if c.get("name") == name] if path.exists() else []

    def chat(self, ref="beta"):
        cid = self.client.post("/api/desk/chats", json={}).json()["id"]
        assert self.client.put(f"/api/desk/chats/{cid}/scope", json={"items": [{"kind": "company", "ref": ref}]}).status_code == 200
        return cid

    def ask(self, cid, question="capex", mode="quick"):
        r = self.client.post(f"/api/desk/chats/{cid}/turns", json={"question": question, "mode": mode})
        assert r.status_code == 202, r.text
        return r.json()["turn_id"]

    def wait(self, tid, timeout=30.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            out = self.client.get(f"/api/desk/turns/{tid}").json()
            if out["status"] != "running":
                return out
            time.sleep(0.05)
        raise AssertionError(f"turn {tid} still running")


@pytest.fixture
def env(pg, tmp_path, monkeypatch):
    folder = tmp_path / "standins"
    (folder / "model").mkdir(parents=True)
    docs = tmp_path / "documents"
    (docs / "beta" / "other").mkdir(parents=True)
    (docs / "beta" / "other" / "beta-2025.txt").write_text(
        "Capital expenditure in 2025 amounted to EUR 6,400 million.\nInvestments in renewables and grids: "
        f"EUR 1,900 million.\n{GROUP}\n")
    for name, value in {"STANDINS_DIR": folder, "DOCUMENTS_DIR": docs, "RUNS_DIR": tmp_path / "runs",
                        "DOCUMENT_STORE_DIR": tmp_path / "store", "HYBRID_RETRIEVAL_ENABLED": "false",
                        "RERANK_ENABLED": "false"}.items():
        monkeypatch.setenv(f"ARP_{name}", str(value))
    monkeypatch.delenv("ARP_ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    app.dependency_overrides[current_user] = lambda: ALICE
    with TestClient(app) as c:  # one event loop for the test, so a background turn keeps running
        e = Env(c, folder)
        e.answer()
        yield e
    app.dependency_overrides.pop(current_user, None)


def test_ac17_quick_never_reranks(env, monkeypatch):
    monkeypatch.setenv("ARP_RERANK_ENABLED", "true")
    get_settings.cache_clear()
    out = env.wait(env.ask(env.chat()))
    assert out["status"] == "done"
    assert next(s for s in out["stages"] if s["name"] == "rank")["status"] == "skipped"
    assert out["sources"] and all("rerank" not in s["scores"] for s in out["sources"])


def test_ac29_first_question_names_the_chat(env):
    cid = env.chat()
    question = "How much capex went to renewables and grids in 2025, and what share of group capex is that?"[:70]
    env.wait(env.ask(cid, question))
    assert env.client.get(f"/api/desk/chats/{cid}").json()["title"] == question[:60]


def test_ac30_stale_running_turn_is_reaped(env):
    cid = env.chat()
    with transaction() as s:
        old = m.DeskTurn(chat_id=cid, user_id="alice", question="old", mode="quick", stages=[],
                         updated_at=datetime.now(UTC) - timedelta(minutes=11))
        s.add(old)
        s.flush()
        old_id = old.id
    new_id = env.ask(cid)
    out = env.client.get(f"/api/desk/turns/{old_id}").json()
    assert (out["status"], out["error"]) == ("failed", "interrupted")
    env.wait(new_id)


def test_ac31_prompt_holds_earlier_questions(env):
    cid = env.chat()
    env.wait(env.ask(cid, "first question about capex"))
    env.wait(env.ask(cid, "second question about grids"))
    env.wait(env.ask(cid, "third"))
    prompt = env.model_calls("DeskAnswer")[-1]["prompt"]
    assert "first question about capex" in prompt and "second question about grids" in prompt


def test_ac85_chat_list_holds_20(env):
    for _ in range(21):
        assert env.client.post("/api/desk/chats", json={}).status_code == 201
    assert len(env.client.get("/api/desk/chats").json()) == 20
