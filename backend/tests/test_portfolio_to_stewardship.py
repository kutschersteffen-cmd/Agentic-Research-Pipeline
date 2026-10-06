"""Process gap #4: Risk Monitoring hands on to the rest of the process --
held companies become a universe, and open alerts become stewardship
monitoring triggers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api.deps import get_portfolio_store, settings_dep
from arp.api.routers import portfolio as portfolio_router
from arp.config import Settings
from arp.schemas.portfolio_monitoring import Alert, AlertCategory, AlertStatus
from arp.stewardship import monitoring
from arp.stewardship.process import load_sample
from arp.storage.portfolio_store import PortfolioStore

pytestmark = pytest.mark.usefixtures("sample_house_universe")


def test_held_companies_become_a_universe(tmp_path):
    settings = Settings(runs_dir=tmp_path / "runs", portfolios_dir=tmp_path / "portfolios")
    store = PortfolioStore(settings.portfolios_dir)
    app = FastAPI()
    app.include_router(portfolio_router.router)
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[get_portfolio_store] = lambda: store
    client = TestClient(app)
    assert client.post("/api/portfolio/universe", json={}).status_code == 404  # nothing held yet

    client.post("/api/portfolio/demo/seed")
    portfolio_id = client.get("/api/portfolio/portfolios").json()[0]["portfolio_id"]
    res = client.post("/api/portfolio/universe", json={"portfolio_ids": [portfolio_id]})
    assert res.status_code == 200, res.text
    body = res.json()
    saved = json.loads(Path(body["path"]).read_text())
    assert len(saved) == body["company_count"] > 0
    held = {c["company_id"] for c in saved}
    assert held <= {c.company_id for c in store.list_companies()}


def _alert(company_id: str, category: AlertCategory, status: AlertStatus = AlertStatus.OPEN) -> Alert:
    return Alert(category=category, scope_id=company_id, company_id=company_id, status=status)


def test_open_portfolio_alerts_raise_stewardship_triggers(tmp_path):
    alerts = [
        _alert("SYN02", AlertCategory.NEWS_CONTROVERSY),
        _alert("SYN03", AlertCategory.THRESHOLD_BREACH, AlertStatus.ESCALATED),
        _alert("SYN04", AlertCategory.NEWS_CONTROVERSY, AlertStatus.RESOLVED),  # closed: no trigger
    ]
    sample = load_sample(tmp_path / "fw", votes=[], alerts=alerts)
    raised = {
        (t["issuer_id"], t["rule"])
        for t in monitoring.evaluate(monitoring.load_graph(), sample, [])
        if t["rule"].startswith("portfolio_")
    }
    assert raised == {("SYN02", "portfolio_news_controversy"), ("SYN03", "portfolio_threshold_breach")}
