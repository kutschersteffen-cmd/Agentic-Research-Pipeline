import hashlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.auth import Principal, current_user
from arp.api.routers import bi, portfolio
from arp.bi.service import DesignResult
from arp.config import Settings
from arp.portfolio.qa_agent import _ParsedQuestion
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef
from arp.storage.portfolio_store import PortfolioStore

APPROVER = Principal(user_id="u_secret", name="Ann", role="approver")
ANALYST = Principal(user_id="u_an", name="Al", role="analyst")
RESOLVABLE = _ParsedQuestion(resolvable=True, security_filter={"company_id": "bmw"})


class _LLM:
    def __init__(self, *outputs):
        self.outputs = list(outputs)

    async def complete_structured(self, **kw):
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out, None


def _app(tmp_path, llm, principal=APPROVER, superset=None):
    store = PortfolioStore(tmp_path)
    store.save_portfolio(Portfolio(portfolio_id="p1", name="P1"))
    store.save_security(SecurityRef(security_id="bmw_eq", name="BMW", asset_class="equity", currency="EUR", company_id="bmw"))
    store.save_company(CompanyRef(company_id="bmw", name="BMW AG"))
    store.save_snapshot("p1", "2026-01-01", [Holding(
        portfolio_id="p1", security_id="bmw_eq", as_of_date="2026-01-01", quantity=1, price=10, market_value=10,
        fx_rate_to_eur=1.0, market_value_eur=10)])
    settings = Settings(portfolios_dir=tmp_path)
    app = FastAPI()
    app.include_router(portfolio.router)
    app.include_router(bi.router)
    app.dependency_overrides[deps.get_portfolio_store] = lambda: store
    app.dependency_overrides[deps.get_llm_client] = lambda: llm
    app.dependency_overrides[deps.settings_dep] = lambda: settings
    app.dependency_overrides[deps.get_superset_client] = lambda: superset
    app.dependency_overrides[current_user] = lambda: principal
    return TestClient(app, raise_server_exceptions=False), settings


def _rows(settings):
    from arp.storage.jsonl_io import read_jsonl
    return read_jsonl(settings.portfolios_dir / "qa_audit.jsonl")


def test_every_answer_has_an_audit_row(tmp_path):
    c, s = _app(tmp_path, _LLM(RESOLVABLE, RESOLVABLE, RESOLVABLE))
    texts = [c.post("/api/portfolio/ask", json={"question": f"q{i}"}).json()["answer_text"] for i in range(3)]
    rows = _rows(s)
    assert [r["answer_sha256"] for r in rows] == [hashlib.sha256(t.encode()).hexdigest() for t in texts]
    assert [r["question"] for r in rows] == ["q0", "q1", "q2"]


def test_unresolvable_and_error_still_audited(tmp_path):
    c, s = _app(tmp_path, _LLM(_ParsedQuestion(resolvable=False, clarification_needed="which?"), RuntimeError("boom")))
    assert c.post("/api/portfolio/ask", json={"question": "a"}).status_code == 200
    assert c.post("/api/portfolio/ask", json={"question": "b"}).status_code == 500  # still raised
    ok, bad = _rows(s)
    assert ok["error"] is None and ok["answer_sha256"] == hashlib.sha256(b"").hexdigest()
    assert "boom" in bad["error"]


def test_audit_write_failure_does_not_break_answer(tmp_path):
    c, s = _app(tmp_path, _LLM(RESOLVABLE))
    (tmp_path / "qa_audit.jsonl").mkdir()  # appending to a directory fails
    assert c.post("/api/portfolio/ask", json={"question": "a"}).status_code == 200


def test_vintage_holds_holdings_as_of(tmp_path):
    c, s = _app(tmp_path, _LLM(RESOLVABLE))
    body = c.post("/api/portfolio/ask", json={"question": "a"}).json()
    assert body["vintage"] == {"holdings_as_of": "2026-01-01"}
    assert _rows(s)[0]["vintage"] == {"holdings_as_of": "2026-01-01"}


def test_audit_endpoint_approver_only_and_no_user_id(tmp_path):
    c, s = _app(tmp_path, _LLM(RESOLVABLE, RESOLVABLE))
    c.post("/api/portfolio/ask", json={"question": "first"})
    c.post("/api/portfolio/ask", json={"question": "second"})
    assert _rows(s)[0]["user_id"] == "u_secret"
    got = c.get("/api/portfolio/qa-audit").json()
    assert [r["question"] for r in got] == ["second", "first"]
    assert all("user_id" not in r and r["user_name"] == "Ann" for r in got)
    c2, _ = _app(tmp_path, _LLM(), principal=ANALYST)
    assert c2.get("/api/portfolio/qa-audit").status_code == 403


def test_bi_ask_audited(tmp_path, monkeypatch):
    async def fake_ask(question, llm, client):
        return DesignResult(dashboard_id=7, slug="arp-scratch", url="http://x/d/7", plan=None)

    monkeypatch.setattr("arp.bi.service.ask_chart", fake_ask)
    c, s = _app(tmp_path, _LLM())
    assert c.post("/api/bi/ask", json={"question": "exposure?"}).status_code == 200
    (row,) = _rows(s)
    assert row["endpoint"] == "bi.ask" and row["user_name"] == "Ann"
    assert row["vintage"] == {"slug": "arp-scratch", "dashboard_id": 7}
