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
