from arp.discovery.identity_graph import resolve_company_identity
from arp.schemas.common import CompanyRef
from arp.schemas.discovery import EdgarNameMatch, IdentityAdjudication, IdentityVerdict


class _FakeEdgar:
    def __init__(self, matches_by_query: dict[str, list[EdgarNameMatch]] | None = None):
        self._matches = matches_by_query or {}
        self.queries: list[str] = []

    async def search_by_name(self, name, limit=5):
        self.queries.append(name)
        return self._matches.get(name, [])[:limit]


class _NullSearch:
    async def search(self, query, max_results=5):
        return []


async def test_website_already_known_short_circuits_with_zero_llm_calls(fake_llm):
    llm = fake_llm({})  # empty script -- any LLM call would raise AssertionError
    company = CompanyRef(company_id="acme", name="Acme Corp", website="https://acme.example.com")

    result, usages = await resolve_company_identity(
        company, llm=llm, edgar=_FakeEdgar(), search_client=_NullSearch()
    )

    assert result.verdict == IdentityVerdict.RESOLVED
    assert result.resolved_website == "https://acme.example.com"
    assert result.flagged_for_review is False
    assert usages == []
    assert llm.calls == []


async def test_cik_already_known_short_circuits(fake_llm):
    llm = fake_llm({})
    company = CompanyRef(company_id="acme", name="Acme Corp", cik="123")

    result, _ = await resolve_company_identity(company, llm=llm, edgar=_FakeEdgar(), search_client=_NullSearch())

    assert result.verdict == IdentityVerdict.RESOLVED
    assert result.resolved_cik == "123"


async def test_clean_single_exact_edgar_match_resolves_with_zero_llm_calls(fake_llm):
    """The whole point of this phase's redesign: a direct, unambiguous
    SEC EDGAR name match never touches the LLM at all."""
    llm = fake_llm({})
    edgar = _FakeEdgar({"Acme Corp": [EdgarNameMatch(ticker="ACME", cik="42", title="Acme Corp")]})
    company = CompanyRef(company_id="acme", name="Acme Corp")

    result, usages = await resolve_company_identity(company, llm=llm, edgar=edgar, search_client=_NullSearch())

    assert result.verdict == IdentityVerdict.RESOLVED
    assert result.resolved_cik == "42"
    assert result.confidence == 1.0
    assert result.flagged_for_review is False
    assert usages == []
    assert llm.calls == []


async def test_single_fuzzy_match_is_not_treated_as_clean_and_still_goes_to_the_llm(fake_llm):
    """A single EDGAR hit that isn't an exact title match (e.g. found via
    the substring/fuzzy tiers of search_by_name) is a weaker signal than a
    real exact match and must still be judged, not auto-resolved."""
    adjudication = IdentityAdjudication(
        verdict=IdentityVerdict.RESOLVED, confidence=0.85, resolved_website=None, resolved_cik="42",
        rationale="Substring match is plausible and uncontested.",
    )
    llm = fake_llm({IdentityAdjudication.__name__: [adjudication]})
    edgar = _FakeEdgar({"Acme": [EdgarNameMatch(ticker="ACME", cik="42", title="Acme Corporation Holdings")]})
    company = CompanyRef(company_id="acme", name="Acme")

    result, usages = await resolve_company_identity(company, llm=llm, edgar=edgar, search_client=_NullSearch())

    assert llm.calls == ["IdentityAdjudication"]
    assert len(usages) == 1
    assert result.verdict == IdentityVerdict.RESOLVED


async def test_ambiguous_signals_route_to_uncertain(fake_llm):
    adjudication = IdentityAdjudication(
        verdict=IdentityVerdict.UNCERTAIN, confidence=0.4, resolved_website=None, resolved_cik=None,
        rationale="Two similarly named filers, cannot disambiguate.",
    )
    llm = fake_llm({IdentityAdjudication.__name__: [adjudication]})
    edgar = _FakeEdgar(
        {
            "Acme": [
                EdgarNameMatch(ticker="ACME", cik="1", title="Acme Corp"),
                EdgarNameMatch(ticker="ACM2", cik="2", title="Acme Corporation"),
            ]
        }
    )
    company = CompanyRef(company_id="acme", name="Acme")

    result, usages = await resolve_company_identity(company, llm=llm, edgar=edgar, search_client=_NullSearch())

    assert llm.calls == ["IdentityAdjudication"]
    assert len(usages) == 1
    assert result.verdict == IdentityVerdict.UNCERTAIN
    assert result.flagged_for_review is True


async def test_no_edgar_matches_still_makes_exactly_one_llm_call(fake_llm):
    adjudication = IdentityAdjudication(
        verdict=IdentityVerdict.UNRESOLVED, confidence=0.1, resolved_website=None, resolved_cik=None,
        rationale="No credible match found anywhere.",
    )
    llm = fake_llm({IdentityAdjudication.__name__: [adjudication]})
    company = CompanyRef(company_id="acme", name="Acme")

    result, usages = await resolve_company_identity(company, llm=llm, edgar=_FakeEdgar(), search_client=_NullSearch())

    assert llm.calls == ["IdentityAdjudication"]
    assert len(usages) == 1
    assert result.verdict == IdentityVerdict.UNRESOLVED


async def test_low_confidence_resolved_is_still_flagged_for_review(fake_llm):
    adjudication = IdentityAdjudication(
        verdict=IdentityVerdict.RESOLVED, confidence=0.5, resolved_website=None, resolved_cik=None,
        rationale="Weak match.",
    )
    llm = fake_llm({IdentityAdjudication.__name__: [adjudication]})
    company = CompanyRef(company_id="acme", name="Acme")

    result, _ = await resolve_company_identity(
        company, llm=llm, edgar=_FakeEdgar(), search_client=_NullSearch(), confidence_threshold=0.7
    )

    assert result.verdict == IdentityVerdict.RESOLVED
    assert result.flagged_for_review is True  # confidence below threshold, even though verdict says resolved


async def test_ungrounded_resolved_cik_is_force_downgraded_to_uncertain(fake_llm):
    """The single most important safety-net test: the adjudicator claims a
    CIK that never appeared in the real signals it was given. The
    mechanical check in identity_graph.py must catch this regardless of
    what the LLM said -- mirrors grounding.py never trusting an LLM's
    self-reported citation location."""
    adjudication = IdentityAdjudication(
        verdict=IdentityVerdict.RESOLVED,
        confidence=0.95,
        resolved_website=None,
        resolved_cik="999999",  # never present in any signal below
        rationale="Confident (but hallucinated) match.",
    )
    llm = fake_llm({IdentityAdjudication.__name__: [adjudication]})
    edgar = _FakeEdgar(
        {
            "Acme": [
                EdgarNameMatch(ticker="ACME", cik="42", title="Acme Corp"),
                EdgarNameMatch(ticker="ACM2", cik="43", title="Acme Corporation"),
            ]
        }
    )
    company = CompanyRef(company_id="acme", name="Acme")

    result, _ = await resolve_company_identity(company, llm=llm, edgar=edgar, search_client=_NullSearch())

    assert result.verdict == IdentityVerdict.UNCERTAIN
    assert result.resolved_cik is None
    assert result.flagged_for_review is True
    assert "downgraded" in result.rationale


async def test_ungrounded_resolved_website_is_force_downgraded(fake_llm):
    adjudication = IdentityAdjudication(
        verdict=IdentityVerdict.RESOLVED,
        confidence=0.95,
        resolved_website="https://not-a-real-signal.example.com",
        resolved_cik=None,
        rationale="Confident (but hallucinated) match.",
    )
    llm = fake_llm({IdentityAdjudication.__name__: [adjudication]})
    company = CompanyRef(company_id="acme", name="Acme")

    result, _ = await resolve_company_identity(company, llm=llm, edgar=_FakeEdgar(), search_client=_NullSearch())

    assert result.verdict == IdentityVerdict.UNCERTAIN
    assert result.resolved_website is None


async def test_grounded_website_from_real_search_result_is_accepted(fake_llm, fake_search):
    from arp.discovery.site_finder import SearchResult

    adjudication = IdentityAdjudication(
        verdict=IdentityVerdict.RESOLVED,
        confidence=0.9,
        resolved_website="https://acme.example.com",
        resolved_cik=None,
        rationale="Matches the search result.",
    )
    llm = fake_llm({IdentityAdjudication.__name__: [adjudication]})
    search = fake_search(
        {"Acme investor relations": [SearchResult(title="Acme", url="https://acme.example.com", snippet="")]}
    )
    company = CompanyRef(company_id="acme", name="Acme")

    result, _ = await resolve_company_identity(company, llm=llm, edgar=_FakeEdgar(), search_client=search)

    assert result.verdict == IdentityVerdict.RESOLVED
    assert result.resolved_website == "https://acme.example.com"
