from arp.discovery.identity_agents import (
    adjudicate_identity,
    challenge_identity,
    propose_identity,
    resolve_signals,
)
from arp.discovery.site_finder import SearchResult
from arp.schemas.discovery import (
    EdgarNameMatch,
    IdentityAdjudication,
    IdentityCandidate,
    IdentityChallenge,
    IdentitySignals,
    IdentityVerdict,
)


class _FakeEdgar:
    def __init__(self, matches_by_query: dict[str, list[EdgarNameMatch]]):
        self._matches = matches_by_query
        self.queries: list[str] = []

    async def search_by_name(self, name, limit=5):
        self.queries.append(name)
        return self._matches.get(name, [])[:limit]


async def test_propose_identity_returns_scripted_candidate(fake_llm):
    candidate = IdentityCandidate(legal_name_guesses=["Acme Corp"], ticker_guess="ACME", search_queries=["Acme Corp"])
    llm = fake_llm({IdentityCandidate.__name__: [candidate]})

    result, usage = await propose_identity("Acme", llm, country_hint="US", sector_hint="Industrials")

    assert result == candidate
    assert "Acme" in llm.prompts[0]
    assert "US" in llm.prompts[0]
    assert "Industrials" in llm.prompts[0]


async def test_propose_identity_omits_hints_when_absent(fake_llm):
    candidate = IdentityCandidate()
    llm = fake_llm({IdentityCandidate.__name__: [candidate]})

    await propose_identity("Acme", llm)

    assert "Country:" not in llm.prompts[0]
    assert "Sector:" not in llm.prompts[0]


async def test_resolve_signals_merges_and_dedupes_edgar_matches_across_guesses():
    m1 = EdgarNameMatch(ticker="ACME", cik="1", title="Acme Corp")
    m2 = EdgarNameMatch(ticker="ACM2", cik="2", title="Acme Corporation")
    edgar = _FakeEdgar({"Acme": [m1], "Acme Corp": [m1, m2], "ACME": [m1]})
    candidate = IdentityCandidate(legal_name_guesses=["Acme Corp"], ticker_guess="ACME", search_queries=[])

    signals = await resolve_signals("Acme", candidate, edgar=edgar, search_client=_NullSearch())

    assert {m.cik for m in signals.edgar_matches} == {"1", "2"}
    assert "Acme" in edgar.queries  # searched by the original name too, not just guesses


class _NullSearch:
    async def search(self, query, max_results=5):
        return []


async def test_resolve_signals_dedupes_search_results_across_queries(fake_search):
    hit = SearchResult(title="Acme IR", url="https://acme.example.com/investors", snippet="Investor relations.")
    search = fake_search({"query one": [hit], "query two": [hit]})
    candidate = IdentityCandidate(search_queries=["query one", "query two"])
    edgar = _FakeEdgar({})

    signals = await resolve_signals("Acme", candidate, edgar=edgar, search_client=search)

    assert len(signals.search_results) == 1
    assert signals.search_results[0].url == "https://acme.example.com/investors"


async def test_resolve_signals_falls_back_to_default_queries_when_candidate_has_none(fake_search):
    hit = SearchResult(title="Acme IR", url="https://acme.example.com", snippet="")
    search = fake_search({"Acme investor relations": [hit]})
    candidate = IdentityCandidate(search_queries=[])
    edgar = _FakeEdgar({})

    signals = await resolve_signals("Acme", candidate, edgar=edgar, search_client=search)

    assert len(signals.search_results) == 1
    assert "Acme investor relations" in search.queries


async def test_challenge_identity_returns_scripted_challenge(fake_llm):
    challenge = IdentityChallenge(concerns=["Multiple similarly named filers"], lean=IdentityVerdict.UNCERTAIN)
    llm = fake_llm({IdentityChallenge.__name__: [challenge]})
    signals = IdentitySignals(
        edgar_matches=[EdgarNameMatch(ticker="ACME", cik="1", title="Acme Corp")],
        search_results=[],
    )

    result, usage = await challenge_identity("Acme", IdentityCandidate(), signals, llm)

    assert result == challenge
    assert "ticker=ACME" in llm.prompts[0]


async def test_challenge_identity_reports_no_matches(fake_llm):
    challenge = IdentityChallenge(concerns=[], lean=IdentityVerdict.UNRESOLVED)
    llm = fake_llm({IdentityChallenge.__name__: [challenge]})
    signals = IdentitySignals(edgar_matches=[], search_results=[])

    await challenge_identity("Acme", IdentityCandidate(), signals, llm)

    assert "none found" in llm.prompts[0]


async def test_adjudicate_identity_includes_challenge_in_prompt(fake_llm):
    adjudication = IdentityAdjudication(
        verdict=IdentityVerdict.RESOLVED, confidence=0.9, resolved_website="https://acme.example.com",
        resolved_cik="1", rationale="Clean single match.",
    )
    llm = fake_llm({IdentityAdjudication.__name__: [adjudication]})
    signals = IdentitySignals(edgar_matches=[], search_results=[])
    challenge = IdentityChallenge(concerns=["some concern"], lean=IdentityVerdict.UNCERTAIN)

    result, usage = await adjudicate_identity("Acme", IdentityCandidate(), signals, challenge, llm)

    assert result == adjudication
    assert "some concern" in llm.prompts[0]
    assert "uncertain" in llm.prompts[0]
