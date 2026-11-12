from arp.portfolio import qa_agent
from arp.portfolio.qa_agent import _ParsedQuestion
from arp.schemas.common import CompanyRef
from arp.schemas.portfolio import Holding, Portfolio, SecurityRef
from arp.storage.portfolio_store import PortfolioStore


def _setup(tmp_path):
    store = PortfolioStore(tmp_path)
    securities = {"bmw_eq": SecurityRef(security_id="bmw_eq", name="BMW", asset_class="equity", currency="EUR", company_id="bmw")}
    companies = {"bmw": CompanyRef(company_id="bmw", name="BMW AG")}
    store.save_portfolio(Portfolio(portfolio_id="p1", name="P1"))
    store.save_snapshot(
        "p1", "2026-01-01",
        [Holding(portfolio_id="p1", security_id="bmw_eq", as_of_date="2026-01-01", quantity=1, price=1_000_000, market_value=1_000_000, fx_rate_to_eur=1.0, market_value_eur=1_000_000)],
    )
    return store, securities, companies


async def test_answer_question_resolvable_computes_real_number(tmp_path, fake_llm):
    store, securities, companies = _setup(tmp_path)
    parsed = _ParsedQuestion(resolvable=True, security_filter={"company_id": "bmw"}, group_by="portfolio_id", metric="market_value_sum")
    llm = fake_llm({"_ParsedQuestion": [parsed]})

    answer, _usage = await qa_agent.answer_question("How much BMW exposure do we have?", llm, store, securities, companies)

    assert answer.resolvable is True
    assert answer.result.total_market_value_eur == 1_000_000
    assert "1,000,000" in answer.answer_text
    # the LLM only chose the query; the spec it produced is inspectable, not just the answer text
    assert answer.spec.security_filter == {"company_id": "bmw"}


async def test_answer_question_unresolvable_asks_for_clarification(tmp_path, fake_llm):
    store, securities, companies = _setup(tmp_path)
    parsed = _ParsedQuestion(resolvable=False, clarification_needed="Which company do you mean?")
    llm = fake_llm({"_ParsedQuestion": [parsed]})

    answer, _usage = await qa_agent.answer_question("What's the exposure?", llm, store, securities, companies)

    assert answer.resolvable is False
    assert answer.clarification_needed == "Which company do you mean?"
    assert answer.result is None


async def test_weighted_avg_vintage_holds_observation_dates(tmp_path, fake_llm):
    from arp.schemas.portfolio import DataPointObservation

    store, securities, companies = _setup(tmp_path)
    for day in ("2025-12-01", "2025-12-15"):
        store.append_observation(DataPointObservation(
            company_id="bmw", field_id="f1", field_name="F1", value=1.0, source="internal_api", observed_at=day))
    parsed = _ParsedQuestion(resolvable=True, metric="weighted_avg_datapoint", data_point_field_id="f1")

    answer, _usage = await qa_agent.answer_question("avg f1?", fake_llm({"_ParsedQuestion": [parsed]}), store, securities, companies)

    assert answer.vintage == {"holdings_as_of": "2026-01-01", "observation_dates": ["2025-12-15"]}


async def test_portfolio_named_by_its_display_name_is_resolved_to_its_id(tmp_path, fake_llm):
    """Seen live: the screen scopes a question by display name ("Sustainable Leaders Fund"); the filter matched
    no portfolio_id and the answer was a confident "EUR 0"."""
    store, securities, companies = _setup(tmp_path)
    store.save_portfolio(Portfolio(portfolio_id="p1", name="Core Equity Europe"))
    llm = fake_llm({"_ParsedQuestion": [_ParsedQuestion(resolvable=True, portfolio_filter=["core equity europe"], group_by="company_id")]})

    answer, _usage = await qa_agent.answer_question("What is our largest holding?", llm, store, securities, companies)

    assert answer.spec.portfolio_filter == ["p1"]
    assert answer.result.total_market_value_eur == 1_000_000


async def test_unknown_portfolio_asks_instead_of_answering_zero(tmp_path, fake_llm):
    store, securities, companies = _setup(tmp_path)
    llm = fake_llm({"_ParsedQuestion": [_ParsedQuestion(resolvable=True, portfolio_filter=["Growth Fund"])]})

    answer, _usage = await qa_agent.answer_question("How much do we hold in Growth Fund?", llm, store, securities, companies)

    assert answer.resolvable is False
    assert answer.result is None
    assert answer.clarification_needed == "No portfolio is called 'Growth Fund'. Known portfolios: P1 (p1)."


async def test_a_data_point_named_by_its_label_is_resolved_to_its_field_id(tmp_path, fake_llm):
    """Seen live: "What is the WACI of each portfolio?" was refused with "Please give the field ID for carbon
    intensity". The model now gets the field list, and a field named by its label is mapped in code."""
    from arp.schemas.portfolio import DataPointObservation

    store, securities, companies = _setup(tmp_path)
    store.append_observation(DataPointObservation(company_id="bmw", field_id="climate_carbon_intensity", field_name="Carbon intensity",
                                                  value=120.0, source="internal_api", observed_at="2025-12-15"))
    parsed = _ParsedQuestion(resolvable=True, metric="weighted_avg_datapoint", data_point_field_id="Carbon Intensity")

    answer, _usage = await qa_agent.answer_question("WACI per portfolio?", fake_llm({"_ParsedQuestion": [parsed]}), store, securities, companies)

    assert answer.spec.data_point_field_id == "climate_carbon_intensity"
    assert answer.resolvable is True
    assert "climate_carbon_intensity: Carbon intensity" in qa_agent._field_directory()
