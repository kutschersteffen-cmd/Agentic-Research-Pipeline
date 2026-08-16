from arp.discovery.identity_agents import adjudicate_identity, gather_signals
from arp.discovery.site_finder import SearchResult
from arp.schemas.discovery import EdgarNameMatch, IdentityAdjudication, IdentitySignals, IdentityVerdict


class _FakeEdgar:
    def __init__(self, matches_by_query: dict[str, list[EdgarNameMatch]]):
        self._matches = matches_by_query
        self.queries: list[str] = []

    async def search_by_name(self, name, limit=5):
        self.queries.append(name)
        return self._matches.get(name, [])[:limit]


class _NullSearch:
    async def search(self, query, max_results=5):
        return []


async def test_gather_signals_looks_up_edgar_by_the_raw_company_name_only():
    m1 = EdgarNameMatch(ticker="ACME", cik="1", title="Acme Corp")
    edgar = _FakeEdgar({"Acme": [m1]})

    signals = await gather_signals("Acme", edgar=edgar, search_client=_NullSearch())

    assert signals.edgar_matches == [m1]
    assert edgar.queries == ["Acme"]  # exactly one lookup, no guess-expansion


async def test_gather_signals_dedupes_search_results_across_default_queries(fake_search):
    hit = SearchResult(title="Acme IR", url="https://acme.example.com/investors", snippet="Investor relations.")
    search = fake_search(
        {"Acme investor relations": [hit], "Acme official website": [hit]}
    )
    edgar = _FakeEdgar({})

    signals = await gather_signals("Acme", edgar=edgar, search_client=search)

    assert len(signals.search_results) == 1
    assert signals.search_results[0].url == "https://acme.example.com/investors"
    assert set(search.queries) == {"Acme investor relations", "Acme official website"}


async def test_gather_signals_with_no_matches_returns_empty_signals():
    signals = await gather_signals("Nonexistent Co", edgar=_FakeEdgar({}), search_client=_NullSearch())
    assert signals.edgar_matches == []
    assert signals.search_results == []


async def test_adjudicate_identity_returns_scripted_adjudication(fake_llm):
    adjudication = IdentityAdjudication(
        verdict=IdentityVerdict.RESOLVED, confidence=0.9, resolved_website=None, resolved_cik="1",
        rationale="Single unambiguous match.",
    )
    llm = fake_llm({IdentityAdjudication.__name__: [adjudication]})
    signals = IdentitySignals(edgar_matches=[EdgarNameMatch(ticker="ACME", cik="1", title="Acme Corp")])

    result, usage = await adjudicate_identity("Acme", signals, llm)

    assert result == adjudication
    assert "Acme" in llm.prompts[0]
    assert "ticker=ACME" in llm.prompts[0]


async def test_adjudicate_identity_reports_no_matches_in_the_prompt(fake_llm):
    adjudication = IdentityAdjudication(
        verdict=IdentityVerdict.UNRESOLVED, confidence=0.1, resolved_website=None, resolved_cik=None,
        rationale="No credible match.",
    )
    llm = fake_llm({IdentityAdjudication.__name__: [adjudication]})

    await adjudicate_identity("Acme", IdentitySignals(), llm)

    assert "none found" in llm.prompts[0]
