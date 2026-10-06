from __future__ import annotations

import asyncio

from arp.smart_search import SearchFilter, apply, smart_search

ISSUES = [
    {"source": "feed", "severity": "block", "title": "ESG data · default: last load failed", "detail": "fetch failed", "subject": "default"},
    {"source": "security_master", "severity": "block", "title": "US0378331005: not in security master", "detail": "held by PF-1 (portfolio)", "subject": "US0378331005"},
    {"source": "check", "severity": "warn", "title": "Acme · scope1: yoy_jump", "detail": "", "subject": "Acme"},
]
OUTPUTS = [
    {"kind": "taxonomy", "id": "t1", "name": "Water", "status": "ratified", "used_by": []},
    {"kind": "taxonomy", "id": "t2", "name": "Grid", "status": "draft", "used_by": [{"kind": "run", "id": "r1"}]},
    {"kind": "run", "id": "r1", "name": "theme · Grid", "status": "completed", "used_by": []},
]
FEEDS = [
    {"feed": "news", "source_id": "default", "stale": True, "last_load": {"status": "failed"}},
    {"feed": "holdings", "source_id": "PF-1", "stale": False, "last_load": {"status": "ok"}},
]
LISTS = {"issues": ISSUES, "outputs": OUTPUTS, "feeds": FEEDS}


def test_filters_are_applied_by_code():
    assert [r["subject"] for r in apply(SearchFilter(source="security_master"), **LISTS)] == ["US0378331005"]
    assert len(apply(SearchFilter(severity="block"), **LISTS)) == 2
    assert [r["subject"] for r in apply(SearchFilter(contains="pf-1"), **LISTS)] == ["US0378331005"]  # matches the detail
    assert [r["id"] for r in apply(SearchFilter(target="outputs", unused=True), **LISTS)] == ["t1", "r1"]
    assert [r["id"] for r in apply(SearchFilter(target="outputs", kind="taxonomy", status="Draft"), **LISTS)] == ["t2"]
    assert [r["feed"] for r in apply(SearchFilter(target="feeds", behind=True), **LISTS)] == ["news"]
    assert [r["feed"] for r in apply(SearchFilter(target="feeds", failed=False), **LISTS)] == ["holdings"]


def test_the_model_only_picks_the_filter(fake_llm):
    llm = fake_llm({"SearchFilter": [SearchFilter(target="outputs", unused=True), SearchFilter(resolvable=False, clarification_needed="ask about issues")]})
    answer, _ = asyncio.run(smart_search("outputs nobody uses", llm, **LISTS))
    assert answer.answer_text == "2 outputs (unused=True)." and [r["id"] for r in answer.rows] == ["t1", "r1"]
    assert "t1" not in llm.prompts[0], "the model never sees the rows"
    answer, _ = asyncio.run(smart_search("did scope 1 jump?", llm, **LISTS))
    assert not answer.resolvable and answer.rows == [] and answer.clarification_needed == "ask about issues"


def test_route_answers_and_audits(tmp_path, fake_llm):
    from fastapi.testclient import TestClient

    from arp.api.auth import current_user
    from arp.api.deps import get_llm_client, get_portfolio_store, settings_dep
    from arp.api.main import app
    from arp.config import Settings
    from arp.storage.portfolio_store import PortfolioStore
    from tests.conftest import PRINCIPAL

    settings = Settings(runs_dir=tmp_path / "runs", identifier_map_path=tmp_path / "idmap.jsonl", portfolios_dir=tmp_path / "pf")
    app.dependency_overrides.update({
        settings_dep: lambda: settings, current_user: lambda: PRINCIPAL, get_portfolio_store: lambda: PortfolioStore(tmp_path / "pf"),
        get_llm_client: lambda: fake_llm({"SearchFilter": [SearchFilter(target="feeds", feed="news")]}),
    })
    try:
        r = TestClient(app).post("/api/smart-search", json={"question": "is news current?"})
        assert r.status_code == 200, r.text
        assert r.json()["filter"]["feed"] == "news" and [f["feed"] for f in r.json()["rows"]] == ["news"]
    finally:
        app.dependency_overrides.clear()
