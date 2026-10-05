"""The house program can cover the companies held in the portfolios instead
of the synthetic sample, so stewardship shares company ids with Risk
Monitoring, Proxy Voting and Decision Studio and their handoffs match."""

from __future__ import annotations

import asyncio
import json

import pytest

from arp.portfolio.mock_data import generate_demo_dataset
from arp.schemas.portfolio_monitoring import Alert, AlertCategory
from arp.stewardship import monitoring, process
from arp.stewardship.universe import HouseUniverseSetting, from_portfolio
from arp.storage.portfolio_store import PortfolioStore


@pytest.fixture(scope="module")
def universe(tmp_path_factory):
    store = PortfolioStore(tmp_path_factory.mktemp("pf"))
    asyncio.run(generate_demo_dataset(store, 0.85))
    return from_portfolio(store)


def test_held_companies_in_the_sample_shape(universe):
    assert universe["source"] == "portfolio"
    ids = {i["issuer_id"] for i in universe["issuers"]}
    assert "bmw" in ids and not any(i.startswith("SYN") for i in ids)
    weights = [i["holding"]["index_weight_pct"] for i in universe["issuers"]]
    assert sum(weights) == pytest.approx(100, abs=0.1)
    assert all("score.clti" in i["fields"] for i in universe["issuers"])  # placeholder, labelled in the note
    assert "placeholders" in universe["note"]


def test_a_portfolio_alert_reaches_stewardship_on_held_companies(universe, tmp_path):
    alert = Alert(category=AlertCategory.NEWS_CONTROVERSY, scope_id="bmw", company_id="bmw")
    sample = process.load_sample(tmp_path / "fw", votes=[], alerts=[alert], base=json.loads(json.dumps(universe)))
    raised = [t for t in monitoring.evaluate(monitoring.load_graph(), sample, []) if t["rule"] == "portfolio_news_controversy"]
    assert [t["issuer_id"] for t in raised] == ["bmw"]


def test_the_flow_runs_and_labels_portfolio_figures(universe, tmp_path, monkeypatch):
    monkeypatch.setattr(process, "house_universe", lambda: json.loads(json.dumps(universe)))
    stages = process.flow(process.HOUSE, process.StreamStore(tmp_path / "s"), [], 45, votes=[])["stages"]
    sources = {m["source"] for s in stages for m in s["metrics"]}
    assert "sample" not in sources and "portfolio" in sources
    monitored = next(m for m in stages[0]["metrics"] if m["label"] == "Companies monitored")
    assert monitored["value"] == len(universe["issuers"])


def test_the_setting_needs_a_known_source_and_a_name(tmp_path):
    setting = HouseUniverseSetting(tmp_path)
    assert setting.get()["source"] == "sample"
    with pytest.raises(ValueError):
        setting.set("benchmark", "A. Reviewer")
    with pytest.raises(ValueError):
        setting.set("portfolio", " ")
    assert setting.set("portfolio", "A. Reviewer")["source"] == "portfolio"
    assert setting.get()["set_by"] == "A. Reviewer"
    assert process.StreamStore(tmp_path).list() == []  # the setting is not mistaken for a client stream
