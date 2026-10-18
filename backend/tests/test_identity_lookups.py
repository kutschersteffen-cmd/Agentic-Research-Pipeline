"""Identity run lookups: derived LEI (GLEIF by ISIN), Wikidata + site check, GLEIF name signals, resolved LEI."""

from __future__ import annotations

from collections import defaultdict

import httpx
import pytest

from arp.config import Settings
from arp.discovery import identity_graph, site_check, site_finder
from arp.discovery.identity_graph import resolve_company_identity
from arp.discovery.identity_pipeline import create_identity_run, enriched_universe, execute_identity_run
from arp.orchestration.review_queue import record_review_decision
from arp.schemas.common import CompanyRef
from arp.schemas.discovery import IdentityAdjudication, IdentityVerdict
from arp.storage.run_store import RunStore
from tests.test_identity_graph import _FakeEdgar, _NullSearch

UA = "arp-test/1.0"
LEI = "5299009TESTWERKE0063"
OTHER_LEI = "5299009OTHERCO000060"
ISIN = "DE000TST0006"
H1_URL = "https://www.testwerke.de/"
H1 = '<html><head><title>Testwerke – Startseite</title></head><body><a href="/impressum">Impressum</a></body></html>'
IMPRINT = "<html><body><p>Testwerke AG, Musterstrasse 1, Teststadt</p><p>LEI: 5299009TESTWERKE0063</p></body></html>"
H4 = "<html><head><title>Testwerke AG</title></head><body><p>Welcome</p></body></html>"
H3_URL = "https://www.otherco.co.uk/"
H3 = "<html><head><title>Otherco plc | Home</title></head><body><p>Welcome</p></body></html>"
W = CompanyRef(company_id="w", name="Testwerke AG", lei=LEI, isin=ISIN, country="DE")
W_NO_LEI = W.model_copy(update={"lei": None})
NAME_ONLY = CompanyRef(company_id="w", name="Testwerke AG")


@pytest.fixture(autouse=True)
def _no_ssrf(monkeypatch):
    async def noop(request):
        return None

    for module in (site_check, site_finder, identity_graph):
        monkeypatch.setattr(module, "ssrf_guard_request_hook", noop)


def _gleif_record(lei: str, name: str, country: str) -> dict:
    return {
        "id": lei,
        "attributes": {
            "lei": lei,
            "entity": {"legalName": {"name": name}, "legalAddress": {"country": country}},
            "registration": {"status": "ISSUED"},
        },
    }


W_RECORD = _gleif_record(LEI, "Testwerke AG", "DE")


class _Web:
    """One MockTransport for Wikidata, GLEIF and the testwerke.de site, routed by host; records requests per host."""

    def __init__(self, *, wikidata=None, gleif_isin=None, gleif_name=None, homepage=None, pages=None):
        self.wikidata = wikidata or {}  # Wikidata property -> P856 URLs
        self.gleif_isin = gleif_isin or []  # GLEIF records for the ISIN filter
        self.gleif_name = gleif_name or []  # GLEIF records for the name search
        self.homepage = homepage  # HTML served at H1_URL
        self.pages = pages or {}  # further HTML by exact URL
        self.requests: dict[str, list[httpx.Request]] = defaultdict(list)
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        self.requests[host].append(request)
        if host == "query.wikidata.org":
            query = request.url.params["query"]
            urls = next((u for prop, u in self.wikidata.items() if f"wdt:{prop} " in query), [])
            return httpx.Response(200, json={"results": {"bindings": [{"w": {"value": u}} for u in urls]}})
        if host == "api.gleif.org":
            records = self.gleif_isin if "filter[isin]" in request.url.params else self.gleif_name
            return httpx.Response(200, json={"data": records})
        if host == "www.testwerke.de" and self.homepage is not None:
            if request.url.path == "/":
                return httpx.Response(200, html=self.homepage)
            if request.url.path == "/impressum":
                return httpx.Response(200, html=IMPRINT)
        if str(request.url) in self.pages:
            return httpx.Response(200, html=self.pages[str(request.url)])
        return httpx.Response(404)


async def _run(company, web: _Web, llm):
    return await resolve_company_identity(
        company, llm=llm, edgar=_FakeEdgar(), search_client=_NullSearch(), lookup_user_agent=UA, transport=web.transport
    )


def _adjudication(**update) -> IdentityAdjudication:
    base = IdentityAdjudication(
        verdict=IdentityVerdict.RESOLVED, confidence=0.95, resolved_website=None, resolved_cik=None, rationale="GLEIF match."
    )
    return base.model_copy(update=update)


async def test_ac_13_isin_to_derived_lei(fake_llm):
    web = _Web(gleif_isin=[W_RECORD])
    result, _ = await _run(W_NO_LEI, web, fake_llm({}))
    assert result.derived_lei == LEI
    assert result.match_rule == "exact_lei"
    assert result.resolved_issuer_key == LEI
    assert result.identifiers == {"isin": ISIN}


async def test_ac_14_isin_without_gleif_hit(fake_llm):
    web = _Web()
    llm = fake_llm({IdentityAdjudication.__name__: [_adjudication(verdict=IdentityVerdict.UNRESOLVED, confidence=0.0)]})
    result, _ = await _run(W_NO_LEI, web, llm)
    assert result.derived_lei is None
    assert result.match_rule == "ambiguous"
    assert result.verdict == IdentityVerdict.UNRESOLVED
    assert result.flagged_for_review is True


async def test_ac_15_wikidata_owned_resolves(fake_llm):
    web = _Web(wikidata={"P1278": [H1_URL]}, homepage=H1)
    result, _ = await _run(W, web, fake_llm({}))
    assert result.verdict == IdentityVerdict.RESOLVED
    assert result.flagged_for_review is False
    assert result.resolved_website == H1_URL
    assert result.confidence == 1.0


async def test_ac_74_wikidata_name_match_resolves(fake_llm):
    web = _Web(wikidata={"P1278": [H1_URL]}, homepage=H4)
    result, _ = await _run(W, web, fake_llm({}))
    assert result.verdict == IdentityVerdict.RESOLVED
    assert result.flagged_for_review is False
    assert result.resolved_website == H1_URL
    assert result.confidence == 1.0


async def test_ac_75_wikidata_homepage_404_flags(fake_llm):
    web = _Web(wikidata={"P1278": [H1_URL]})  # no homepage: H1_URL returns 404
    result, _ = await _run(W, web, fake_llm({}))
    assert result.verdict == IdentityVerdict.UNCERTAIN
    assert result.flagged_for_review is True
    assert result.reason_codes == ["match_ambiguous"]
    assert result.resolved_website == H1_URL


async def test_ac_87_wikidata_other_company_rejected(fake_llm):
    web = _Web(wikidata={"P1278": [H3_URL]}, pages={H3_URL: H3})
    result, _ = await _run(W, web, fake_llm({}))
    assert result.verdict == IdentityVerdict.UNCERTAIN
    assert result.flagged_for_review is True
    assert result.reason_codes == ["match_ambiguous"]
    assert result.resolved_website is None


async def test_ac_17_no_wikidata_hit_as_main(fake_llm):
    web = _Web()
    result, _ = await _run(W, web, fake_llm({}))
    assert result.verdict == IdentityVerdict.UNCERTAIN
    assert result.flagged_for_review is True
    assert result.reason_codes == ["match_ambiguous"]
    assert result.match_rule == "exact_lei"
    assert result.resolved_website is None
    assert result.resolved_cik is None


async def test_ac_18_gleif_line_in_prompt(fake_llm):
    web = _Web(gleif_name=[W_RECORD])
    llm = fake_llm({IdentityAdjudication.__name__: [_adjudication(verdict=IdentityVerdict.UNCERTAIN, confidence=0.4)]})
    await _run(NAME_ONLY, web, llm)
    assert f"  - lei={LEI} name='Testwerke AG' country=DE" in llm.prompts[0].splitlines()


async def test_ac_19_unverified_lei_dropped(fake_llm):
    web = _Web(gleif_name=[W_RECORD])
    llm = fake_llm({IdentityAdjudication.__name__: [_adjudication(resolved_lei=OTHER_LEI)]})
    result, _ = await _run(NAME_ONLY, web, llm)
    assert result.resolved_lei is None
    assert result.verdict == IdentityVerdict.UNCERTAIN
    assert result.flagged_for_review is True


def _ac_20_web() -> _Web:
    return _Web(gleif_name=[W_RECORD], wikidata={"P1278": [H1_URL]}, homepage=H1)


def _ac_20_llm(fake_llm):
    return fake_llm({IdentityAdjudication.__name__: [_adjudication(resolved_lei=LEI)]})


async def test_ac_20_resolved_lei_fills_website(fake_llm):
    result, _ = await _run(NAME_ONLY, _ac_20_web(), _ac_20_llm(fake_llm))
    assert result.resolved_lei == LEI
    assert result.resolved_website == H1_URL
    assert result.verdict == IdentityVerdict.RESOLVED
    assert result.confidence == 0.95
    assert result.match_rule == "ambiguous"
    assert result.flagged_for_review is True


async def test_ac_88_resolved_lei_fills_website_from_name_match(fake_llm):
    web = _Web(gleif_name=[W_RECORD], wikidata={"P1278": [H1_URL]}, homepage=H4)
    result, _ = await _run(NAME_ONLY, web, _ac_20_llm(fake_llm))
    assert result.resolved_website == H1_URL
    assert result.verdict == IdentityVerdict.RESOLVED
    assert result.confidence == 0.95
    assert result.match_rule == "ambiguous"
    assert result.flagged_for_review is True


async def test_ac_21_enriched_universe_exports_lei(tmp_path, fake_llm, pg):
    settings = Settings(
        anthropic_api_key="unused",
        runs_dir=tmp_path / "runs",
        identifier_map_path=tmp_path / "idmap.jsonl",
        cache_dir=tmp_path / "cache",
        discovery_user_agent=UA,
    )
    run_store = RunStore(pg, settings.runs_dir)
    run_id = await execute_identity_run(
        create_identity_run([NAME_ONLY], run_store), [NAME_ONLY], llm=_ac_20_llm(fake_llm), settings=settings, run_store=run_store,
        edgar=_FakeEdgar(), search_client=_NullSearch(), transport=_ac_20_web().transport,
    )
    record_review_decision(run_store, run_id, "w", "approve", "reviewer1", None)

    universe = enriched_universe(run_store, run_id)

    assert len(universe) == 1
    assert universe[0].lei == LEI
    assert universe[0].website == H1_URL


async def test_ac_22_supplied_values_as_main(fake_llm):
    company = W.model_copy(update={"website": H1_URL, "cik": "123"})
    result, _ = await _run(company, _Web(wikidata={"P1278": [H1_URL]}, homepage=H1), fake_llm({}))
    assert result.match_rule == "exact_lei"
    assert result.verdict == IdentityVerdict.RESOLVED
    assert result.resolved_website == H1_URL
    assert result.resolved_cik == "123"


async def test_ac_43_owned_path_zero_prompts(fake_llm):
    llm = fake_llm({})
    await _run(W, _Web(wikidata={"P1278": [H1_URL]}, homepage=H1), llm)
    assert llm.prompts == []


async def test_ac_44_supplied_zero_lookups(fake_llm):
    company = W.model_copy(update={"website": H1_URL, "cik": "123"})
    web = _Web(wikidata={"P1278": [H1_URL]}, gleif_isin=[W_RECORD], gleif_name=[W_RECORD], homepage=H1)
    await _run(company, web, fake_llm({}))
    assert web.requests["query.wikidata.org"] == []
    assert web.requests["api.gleif.org"] == []
    assert web.requests["www.testwerke.de"] == []


async def test_ac_45_one_prompt(fake_llm):
    llm = _ac_20_llm(fake_llm)
    await _run(NAME_ONLY, _ac_20_web(), llm)
    assert len(llm.prompts) == 1


async def test_ac_47_supplied_cik_as_main(fake_llm):
    result, _ = await _run(W.model_copy(update={"cik": "123"}), _Web(wikidata={"P1278": [H1_URL]}, homepage=H4), fake_llm({}))
    assert result.match_rule == "exact_lei"
    assert result.verdict == IdentityVerdict.RESOLVED
    assert result.resolved_website is None


async def test_ac_50_no_hit_zero_prompts(fake_llm):
    llm = fake_llm({})
    await _run(W, _Web(), llm)
    assert llm.prompts == []


async def test_ac_51_supplied_cik_no_wikidata(fake_llm):
    web = _Web(wikidata={"P1278": [H1_URL]}, homepage=H4)
    await _run(W.model_copy(update={"cik": "123"}), web, fake_llm({}))
    assert web.requests["query.wikidata.org"] == []


async def test_derived_lei_result_reused_without_gleif(tmp_path, fake_llm, pg):
    settings = Settings(
        anthropic_api_key="unused",
        runs_dir=tmp_path / "runs",
        identifier_map_path=tmp_path / "idmap.jsonl",
        cache_dir=tmp_path / "cache",
        discovery_user_agent=UA,
    )
    run_store = RunStore(pg, settings.runs_dir)
    run = dict(llm=fake_llm({}), settings=settings, run_store=run_store, edgar=_FakeEdgar(), search_client=_NullSearch())
    first = await execute_identity_run(
        create_identity_run([W_NO_LEI], run_store), [W_NO_LEI], **run, transport=_Web(gleif_isin=[W_RECORD]).transport
    )
    web = _Web(gleif_isin=[W_RECORD])
    second = await execute_identity_run(
        create_identity_run([W_NO_LEI], run_store), [W_NO_LEI], **run, previous_run_id=first, transport=web.transport
    )
    assert web.requests["api.gleif.org"] == []
    assert run_store.read_results(second)[0]["derived_lei"] == LEI


async def test_supplied_website_skips_isin_lookup(fake_llm):
    web = _Web(gleif_isin=[W_RECORD])
    result, _ = await _run(W_NO_LEI.model_copy(update={"website": H1_URL}), web, fake_llm({}))
    assert result.match_rule == "supplied"
    assert web.requests["api.gleif.org"] == []
