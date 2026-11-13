"""Showcase defect 1 and 11 (backend): Ask the Portfolio takes the pane's portfolios and dates as request
fields, answers a trend, and says which snapshots, scale and unit it used."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.auth import Principal, current_user
from arp.api.routers import portfolio
from arp.config import Settings
from arp.portfolio import qa_agent
from arp.portfolio.qa_agent import _ParsedQuestion
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import DataPointObservation, Holding, Portfolio, SecurityRef
from arp.storage.portfolio_store import PortfolioStore, portfolio_directories
from tests.conftest import FakeLLMClient

DATES = ["2026-01-31", "2026-04-30", "2026-07-31", "2026-10-31"]
SEC = {"resolvable": True, "group_by": "sector", "metric": "market_value_sum"}
Q = "How much do we hold?"


def _snapshot(store, pid, day, value):
    store.save_snapshot(pid, day, [Holding(
        portfolio_id=pid, security_id="bmw_eq", as_of_date=day, quantity=1, price=value, market_value=value,
        fx_rate_to_eur=1.0, market_value_eur=value)])


def _store(tmp_path) -> PortfolioStore:
    """p1 has four snapshots worth 1, 2, 3, 4 million; p2 has the same dates worth 10 each."""
    store = PortfolioStore(tmp_path)
    store.save_company(CompanyRef(company_id="bmw", name="BMW AG", sector="Autos"))
    store.save_security(SecurityRef(security_id="bmw_eq", name="BMW", asset_class="equity", currency="EUR", company_id="bmw"))
    for pid in ("p1", "p2"):
        store.save_portfolio(Portfolio(portfolio_id=pid, name=pid.upper()))
    for i, day in enumerate(DATES):
        _snapshot(store, "p1", day, (i + 1) * 1_000_000.0)
        _snapshot(store, "p2", day, 10.0)
    return store


async def _answer(store, parse, **kw):
    llm = FakeLLMClient({"_ParsedQuestion": [_ParsedQuestion(**parse)]})
    answer, _usage = await qa_agent.answer_question(Q, llm, store, *portfolio_directories(store), **kw)
    return answer


@pytest.fixture
def client(tmp_path):
    store = _store(tmp_path)
    llm = FakeLLMClient({})
    settings = Settings(portfolios_dir=tmp_path)
    app = FastAPI()
    app.include_router(portfolio.router)
    app.dependency_overrides[deps.get_portfolio_store] = lambda: store
    app.dependency_overrides[deps.get_llm_client] = lambda: llm
    app.dependency_overrides[deps.settings_dep] = lambda: settings
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u1", name="Ann", role="approver")

    def ask(parse=SEC, **fields):
        llm._script["_ParsedQuestion"] = [_ParsedQuestion(**parse)]
        return TestClient(app).post("/api/portfolio/ask", json={"question": Q, "portfolio_ids": ["p1"], **fields})

    ask.audit = lambda: TestClient(app).get("/api/portfolio/qa-audit").json()
    ask.llm = llm
    return ask


def test_as_of_picks_that_snapshot(client):
    body = client(as_of=DATES[1]).json()
    assert body["result"]["as_of"] == DATES[1] and body["vintage"] == {"holdings_as_of": DATES[1]}
    assert body["result"]["total_market_value_eur"] == 2_000_000
    assert body["snapshot_dates"] == [DATES[1]]
    assert body["trend"] is None


def test_as_of_between_snapshots_uses_the_one_before(client):
    body = client(as_of="2026-05-01").json()
    assert body["result"]["as_of"] == "2026-05-01" and body["snapshot_dates"] == [DATES[1]]


def test_question_only_is_answered_as_before(client):
    body = client().json()
    assert body["result"]["as_of"] == DATES[3] and body["vintage"] == {"holdings_as_of": DATES[3]}
    assert body["spec"]["portfolio_filter"] == ["p1"]
    assert body["answer_text"].startswith("Total: EUR 4,000,000 (portfolios=['p1'], no filter, grouped by sector, as of")
    assert (body["scale"], body["unit"]) == ("units", "EUR")


def test_pane_selection_is_the_filter_unless_the_question_names_a_portfolio(client):
    assert client({**SEC, "group_by": "portfolio_id"}).json()["result"]["rows"][0]["group_value"] == "p1"
    assert client({**SEC, "portfolio_filter": ["p2"]}).json()["spec"]["portfolio_filter"] == ["p2"]


@pytest.mark.parametrize("fields, text", [
    ({"as_of": "31/12/2099"}, "as_of must be YYYY-MM-DD"),
    ({"as_of": "2099-12-31"}, "as_of is in the future"),
    ({"date_range": ["2026-13-01", DATES[3]]}, "date_range must be two YYYY-MM-DD dates"),
    ({"date_range": [DATES[3]]}, "date_range must be two YYYY-MM-DD dates"),
    ({"date_range": [DATES[3], DATES[1]]}, "date_range start is after its end"),
    ({"as_of": DATES[1], "date_range": [DATES[1], DATES[3]]}, "send as_of or date_range, not both"),
    ({"portfolio_ids": ["nope"]}, "unknown portfolio_id 'nope'"),
])
def test_bad_fields_are_refused_before_the_model_and_the_audit(client, fields, text):
    r = client(**fields)
    assert r.status_code == 422 and text in r.json()["detail"]
    assert client.audit() == [] and client.llm.calls == []


def test_as_of_before_the_first_snapshot_asks(client):
    body = client(as_of="2026-01-30").json()
    assert (body["resolvable"], body["result"], body["trend"]) == (False, None, None)
    assert body["clarification_needed"] == "No holdings on or before 2026-01-30. The first snapshot is 2026-01-31."


def test_trend_over_a_range(client):
    body = client(date_range=[DATES[1], DATES[3]]).json()
    assert body["resolvable"] is True and body["result"] is None
    assert [p["as_of"] for p in body["trend"]] == DATES[1:]
    assert [p["result"]["total_market_value_eur"] for p in body["trend"]] == [2e6, 3e6, 4e6]
    assert body["snapshot_dates"] == DATES[1:] and body["vintage"] == {"date_range": [DATES[1], DATES[3]]}
    assert body["answer_text"].split("\n") == [
        f"Trend from {DATES[1]} to {DATES[3]}, 3 snapshots (portfolios=['p1'], no filter, grouped by sector):",
        f"  {DATES[1]}: EUR 2,000,000", f"  {DATES[2]}: EUR 3,000,000", f"  {DATES[3]}: EUR 4,000,000"]


def test_range_without_a_snapshot_asks_and_a_future_end_is_allowed(client):
    body = client(date_range=["2001-01-01", "2001-12-31"]).json()
    assert body["resolvable"] is False
    assert body["clarification_needed"] == (
        f"No snapshots between 2001-01-01 and 2001-12-31. Snapshots run from {DATES[0]} to {DATES[3]}.")
    assert len(client(date_range=[DATES[3], "2099-01-01"]).json()["trend"]) == 1


def test_audit_row_has_the_typed_question_and_the_date(client):
    client(as_of=DATES[1])
    row = client.audit()[0]
    assert row["question"] == Q and row["vintage"] == {"holdings_as_of": DATES[1]}


def test_millions_changes_the_text_not_the_figures(client):
    body = client({**SEC, "scale": "millions"}).json()
    assert (body["scale"], body["unit"]) == ("millions", "EUR")
    assert body["result"]["total_market_value_eur"] == 4_000_000
    lines = body["answer_text"].split("\n")
    assert lines[0].startswith("Total: EUR 4.00 million (") and lines[1] == "  Autos: EUR 4.00 million"
    trend = client({**SEC, "scale": "millions"}, date_range=[DATES[2], DATES[3]]).json()
    assert trend["answer_text"].split("\n")[1] == f"  {DATES[2]}: EUR 3.00 million"
    assert "millions" in qa_agent._SYSTEM_PROMPT


def test_unit_follows_the_metric(client):
    waci = {**SEC, "metric": "weighted_avg_datapoint", "data_point_field_id": "climate_carbon_intensity"}
    assert client(waci).json()["unit"] == "tCO2e / EUR M revenue"
    assert client({**waci, "data_point_field_id": "my_field"}).json()["unit"] == ""
    assert client({**SEC, "metric": "count"}).json()["unit"] == ""


async def test_portfolio_without_a_snapshot_asks(tmp_path):  # AC-26
    store = PortfolioStore(tmp_path)
    store.save_portfolio(Portfolio(portfolio_id="empty", name="Empty"))
    answer = await _answer(store, {**SEC, "portfolio_filter": ["empty"]})
    assert answer.resolvable is False and answer.clarification_needed == "No holdings snapshots for that selection."


async def test_trend_lines_for_count_and_weighted_average(tmp_path):  # AC-27
    store = _store(tmp_path)
    store.append_observation(DataPointObservation(
        company_id="bmw", field_id="f1", field_name="F1", value=1.5, source="internal_api", observed_at="2026-06-01"))
    span = {"date_range": (DATES[1], DATES[3]), "portfolio_ids": ["p1"]}
    count = await _answer(store, {**SEC, "metric": "count"}, **span)
    assert count.answer_text.split("\n")[1:] == [f"  {d}: 1 holdings" for d in DATES[1:]]
    avg = await _answer(store, {**SEC, "group_by": "portfolio_id", "metric": "weighted_avg_datapoint",
                                "data_point_field_id": "f1"}, **span)
    assert avg.answer_text.split("\n")[1:] == [
        f"  {DATES[1]}: p1 no data", f"  {DATES[2]}: p1 1.5000", f"  {DATES[3]}: p1 1.5000"]


async def test_trend_has_only_the_scoped_portfolios_dates(tmp_path):  # AC-159
    store = _store(tmp_path)
    store.save_portfolio(Portfolio(portfolio_id="p3", name="P3"))
    _snapshot(store, "p3", "2026-06-15", 5.0)
    answer = await _answer(store, {**SEC, "portfolio_filter": ["p1"]}, date_range=(DATES[0], DATES[3]))
    assert [p.as_of for p in answer.trend] == DATES and answer.snapshot_dates == DATES


# --- showcase-portfolio-data PR 2 (AC-58): an answer built on simulated values says so ---

CI = {"resolvable": True, "group_by": "portfolio_id", "metric": "weighted_avg_datapoint", "data_point_field_id": "climate_carbon_intensity"}


def _observe(store, source, day="2026-01-31"):
    store.append_observation(DataPointObservation(
        company_id="bmw", field_id="climate_carbon_intensity", field_name="CI", value=120.0, source=source,
        observed_at=f"{day}T00:00:00+00:00"))


async def test_an_answer_on_simulated_values_says_simulated(tmp_path):
    store = _store(tmp_path)
    _observe(store, "simulated")
    a = await _answer(store, CI, portfolio_ids=["p1"])
    assert a.answer_text.split("\n")[-1] == "  Simulated: 1 of the 1 company values in scope are simulated ESG data, not real data."
    trend = await _answer(store, CI, portfolio_ids=["p1"], date_range=(DATES[0], DATES[3]))
    assert trend.answer_text.split("\n")[-1].startswith("  Simulated: 1 of the 1 ")


async def test_an_answer_on_real_values_or_on_no_data_point_does_not(tmp_path):
    store = _store(tmp_path)
    _observe(store, "simulated")
    assert "Simulated" not in (await _answer(store, SEC, portfolio_ids=["p1"])).answer_text  # a market value: no data point
    _observe(store, "internal_api")  # a real value wins over the simulated one
    assert "Simulated" not in (await _answer(store, CI, portfolio_ids=["p1"])).answer_text


async def test_the_simulated_count_follows_the_questions_filter(tmp_path):
    store = _store(tmp_path)
    _observe(store, "simulated")
    kept = await _answer(store, {**CI, "security_filter": {"sector": "Autos"}}, portfolio_ids=["p1"])
    assert kept.answer_text.split("\n")[-1].startswith("  Simulated: 1 of the 1 ")
    none = await _answer(store, {**CI, "security_filter": {"sector": "Banks"}}, portfolio_ids=["p1"])
    assert "Simulated" not in none.answer_text  # no holding passes the filter, so no value in the answer is simulated
