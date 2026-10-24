from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from arp.api.auth import Principal, authorize, current_user
from arp.api.deps import get_llm_client, get_portfolio_store, get_run_store, get_stream_store, settings_dep
from arp.api.main import app
from arp.ask import NONE_TEXT, AskRouting
from arp.config import Settings
from arp.db.models import CompanyFact, ReviewDecision, Run
from arp.db.session import transaction
from arp.portfolio.qa_agent import _ParsedQuestion
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef
from arp.smart_search import SearchFilter
from arp.stewardship.benchmark import BenchmarkStore
from arp.stewardship.process import StreamStore
from arp.storage.portfolio_store import PortfolioStore
from tests.conftest import FakeLLMClient
from tests.test_ask_tools import write_benchmark
from tests.test_ask_transition_plan import old_run

BMW_Q = "What is the exposure to BMW in our portfolio?"
ERROR_DETAIL = "Ask could not answer this question. Try again."


def routing(tool, question="q", **kw) -> AskRouting:
    return AskRouting(tool=tool, standalone_question=question, **kw)


BMW_PARSE = _ParsedQuestion(resolvable=True, security_filter={"company_id": "bmw"}, group_by="company_id", metric="market_value_sum")


@pytest.fixture
def env(tmp_path, run_store):
    """Holdings where BMW's lines total EUR 1,234,567.00, a run store, a streams root and an audit file in tmp_path."""
    store = PortfolioStore(tmp_path / "pf")
    store.save_company(CompanyRef(company_id="bmw", name="BMW AG"))
    store.save_security(SecurityRef(security_id="bmw_eq", name="BMW", asset_class="equity", currency="EUR", company_id="bmw"))
    store.save_security(SecurityRef(security_id="bmw_bd", name="BMW 2030", asset_class="corporate_bond", currency="EUR", company_id="bmw"))
    store.save_portfolio(Portfolio(portfolio_id="p1", name="P1"))
    store.save_snapshot("p1", "2026-01-01", [
        Holding(portfolio_id="p1", security_id=sid, as_of_date="2026-01-01", quantity=1, price=v, market_value=v, fx_rate_to_eur=1.0, market_value_eur=v)
        for sid, v in (("bmw_eq", 1_000_000.0), ("bmw_bd", 234_567.0))
    ])
    settings = Settings(runs_dir=tmp_path / "runs", identifier_map_path=tmp_path / "idmap.jsonl", portfolios_dir=tmp_path / "pf")
    streams = StreamStore(tmp_path / "streams")
    llm = FakeLLMClient({})
    app.dependency_overrides.update({
        settings_dep: lambda: settings, get_portfolio_store: lambda: store, get_run_store: lambda: run_store,
        get_stream_store: lambda: streams, get_llm_client: lambda: llm,
    })
    yield {"client": TestClient(app), "llm": llm, "run_store": run_store, "streams": streams, "settings": settings}
    for dep in (settings_dep, get_portfolio_store, get_run_store, get_stream_store, get_llm_client):
        app.dependency_overrides.pop(dep, None)


def script(env, **queues):
    env["llm"]._script.update({k: list(v) for k, v in queues.items()})


def ask(env, question, history=None, **kw):
    body = {"question": question} if history is None else {"question": question, "history": history}
    return env["client"].post("/api/ask", json=body, **kw)


def audit(env) -> list[dict]:
    """Audit rows in call order (the endpoint lists newest first)."""
    return env["client"].get("/api/portfolio/qa-audit").json()[::-1]


def turn(i=0):
    return {"question": f"q{i}", "tool": "portfolio", "standalone_question": f"q{i}"}


def test_portfolio_question_matches_ask_the_portfolio(env):  # AC-1
    script(env, AskRouting=[routing("portfolio", BMW_Q)], _ParsedQuestion=[BMW_PARSE, BMW_PARSE])
    r = ask(env, BMW_Q, [])
    expected = env["client"].post("/api/portfolio/ask", json={"question": BMW_Q}).json()
    assert r.status_code == 200, r.text
    body = r.json()
    for b in (body["portfolio"], expected):
        b["spec"].pop("analytic_id"), b["spec"].pop("created_at")  # a fresh id and timestamp on every call
    assert body["tool"] == "portfolio" and body["portfolio"] == expected
    assert [row["market_value_eur"] for row in body["portfolio"]["result"]["rows"] if row["group_value"] == "bmw"] == [1234567.0]
    assert body["answer_text"] == expected["answer_text"]


def test_smart_search_question_matches_smart_search(env):  # AC-2
    f = SearchFilter(target="feeds", behind=True)
    script(env, AskRouting=[routing("smart_search", "Which feeds are behind?")], SearchFilter=[f, f])
    r = ask(env, "Which feeds are behind?", [])
    expected = env["client"].post("/api/smart-search", json={"question": "Which feeds are behind?"}).json()
    assert r.status_code == 200, r.text
    assert r.json()["tool"] == "smart_search" and r.json()["smart_search"] == expected
    assert r.json()["answer_text"] == expected["answer_text"]


def test_none_tool_text(env):  # AC-19
    script(env, AskRouting=[routing("none")])
    r = ask(env, "What did BMW say about cobalt?")
    assert r.status_code == 200 and r.json()["tool"] == "none" and r.json()["answer_text"] == NONE_TEXT


def test_history_limits(env):  # AC-20
    script(env, AskRouting=[routing("none")])
    assert ask(env, "q", [turn(i) for i in range(5)]).status_code == 200
    assert ask(env, "q", [turn(i) for i in range(6)]).status_code == 422


def test_question_length_limits(env):  # AC-21, Review Focus 4
    script(env, AskRouting=[routing("none")])
    assert ask(env, "x" * 1000).status_code == 200
    for q in ("", "   ", "x" * 1001):
        assert ask(env, q).status_code == 422
    assert env["llm"].calls == ["AskRouting"]


def test_history_turn_rejects_extra_keys(env):  # AC-22
    assert ask(env, "q", [{**turn(), "answer": "EUR 1m"}]).status_code == 422


def test_viewer_is_refused(env):  # AC-23
    viewer = Principal(user_id="u_v", name="Vera", role="viewer")
    app.dependency_overrides.pop(authorize, None)
    app.dependency_overrides[current_user] = lambda: viewer
    assert ask(env, "q").status_code == 403


def test_one_audit_row_per_call(env, tmp_path):  # AC-24
    write_benchmark(env["streams"].root, name="MSCI World")
    bid = BenchmarkStore(env["streams"].root).list()[0]["benchmark_id"]
    old_run(env["run_store"], "tp_1", "2026-10-20T00:00:00+00:00", ["BASF SE"])
    script(
        env,
        AskRouting=[routing("portfolio", BMW_Q), routing("smart_search"), routing("transition_plan", company="BASF"),
                    routing("benchmark_sectors", benchmark_id=bid), routing("none"), routing("portfolio", BMW_Q)],
        _ParsedQuestion=[BMW_PARSE, BMW_PARSE], SearchFilter=[SearchFilter(target="feeds")],
    )
    for q, history in ((BMW_Q, []), ("feeds?", []), ("BASF?", []), ("sectors?", []), ("cobalt?", []),
                       ("now only equities", [{"question": BMW_Q, "tool": "portfolio", "standalone_question": BMW_Q}])):
        assert ask(env, q, history).status_code == 200
    rows = audit(env)
    assert [r["endpoint"] for r in rows] == [
        "ask.portfolio", "ask.smart_search", "ask.transition_plan", "ask.benchmark_sectors", "ask.none", "ask.portfolio",
    ]
    assert rows[-1]["question"] == "now only equities"


def test_routing_failure_is_502_and_audited(env):  # AC-25
    r = ask(env, "q")  # the fake has nothing scripted for AskRouting, so routing raises
    assert r.status_code == 502 and r.json()["detail"] == ERROR_DETAIL
    [row] = audit(env)
    assert row["endpoint"] == "ask.error" and row["error"]


def test_rejected_requests_leave_no_audit_row(env):  # AC-26
    assert ask(env, "").status_code == 422
    app.dependency_overrides.pop(authorize, None)
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u_v", name="Vera", role="viewer")
    assert ask(env, "q").status_code == 403
    app.dependency_overrides[authorize] = app.dependency_overrides[current_user] = lambda: Principal(user_id="u_a", name="A", role="approver")
    assert audit(env) == []


def test_tool_failure_is_502_audited_under_the_tool(env, monkeypatch):  # AC-50
    script(env, AskRouting=[routing("transition_plan", company="BASF")])

    def boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr(env["run_store"], "list_runs", boom)
    r = ask(env, "BASF?")
    assert r.status_code == 502 and r.json()["detail"] == ERROR_DETAIL
    [row] = audit(env)
    assert row["endpoint"] == "ask.transition_plan" and row["error"]


def _counts(env) -> tuple:
    with transaction(env["run_store"].dsn) as s:
        tables = tuple(s.scalar(select(func.count()).select_from(t)) for t in (Run, ReviewDecision, CompanyFact))
    return (*tables, len(BenchmarkStore(env["streams"].root).list()))


def test_ask_only_reads(env):  # AC-28
    write_benchmark(env["streams"].root, name="MSCI World")
    bid = BenchmarkStore(env["streams"].root).list()[0]["benchmark_id"]
    old_run(env["run_store"], "tp_1", "2026-10-20T00:00:00+00:00", ["BASF SE"])
    script(
        env,
        AskRouting=[routing("portfolio", BMW_Q), routing("smart_search"), routing("transition_plan", company="BASF"),
                    routing("benchmark_sectors", benchmark_id=bid), routing("none")],
        _ParsedQuestion=[BMW_PARSE], SearchFilter=[SearchFilter(target="feeds")],
    )
    before = _counts(env)
    for q in ("a", "b", "c", "d", "e"):
        assert ask(env, q).status_code == 200
    assert _counts(env) == before
    assert len(audit(env)) == 5
