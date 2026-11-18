"""Showcase fixes, R&D Lab: features that search the web say when search is down (spec showcase-themes-fixes 3, 4)."""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.routers import taxonomies as taxonomies_router
from arp.config import Settings
from arp.discovery.identity_agents import gather_signals
from arp.discovery.site_finder import DuckDuckGoSearchClient
from arp.research.authority_taxonomy import run
from arp.research.authority_taxonomy.library import LibraryEntry, save_library
from arp.research.taxonomy_sources.news_mining import build_theme_from_news_and_transcripts
from arp.storage.run_store import LegacyRunStore

S2 = "The web search could not be reached, so no new sources were found. Add a URL or upload a document below."
S3_FLAG = "search_unreachable"


class Down:
    def __init__(self):
        self.queries = 0

    async def search(self, query, max_results=5):
        self.queries += 1
        raise httpx.ConnectError("no route to host")


class Empty:
    async def search(self, query, max_results=5):
        return []


def _discover(tmp_path, search_client, library: bool = False):
    if library:
        save_library("hydrogen", [LibraryEntry(url="https://a.org/A", title="A", source_type="agency_report", summary="s",
                                               covers=[], fetchable=True, status="approved")], tmp_path / "lib")
    store = LegacyRunStore(tmp_path / "runs")
    state = run.create_run("Hydrogen", "hydrogen", "", "", False, run_store=store)
    return asyncio.run(run.discover(state.run_id, run_store=store, search_client=search_client, llm=None,
                                    user_agent="t", library_root=tmp_path / "lib"))


def test_authority_run_with_search_down(tmp_path):  # AC-25, AC-26, AC-109
    state = _discover(tmp_path, Down(), library=True)
    assert (state.stage, state.error) == ("awaiting_sources", S2)
    assert [c.url for c in state.candidates] == ["https://a.org/A"]


def test_authority_run_with_empty_search(tmp_path):  # AC-107
    state = _discover(tmp_path, Empty())
    assert (state.stage, state.error) == ("awaiting_sources", None)


@pytest.fixture
def client(tmp_path, monkeypatch):
    settings = Settings(runs_dir=tmp_path / "runs", taxonomies_dir=tmp_path / "tax", anthropic_api_key=None)
    app = FastAPI()
    app.include_router(taxonomies_router.router)
    app.dependency_overrides[deps.settings_dep] = lambda: settings

    def use(search):
        monkeypatch.setattr(taxonomies_router, "build_web_search_client", lambda ua: search)
    c = TestClient(app)
    c.use_search = use
    return c


def test_fund_search_down(client):  # AC-28
    client.use_search(Down())
    body = client.post("/api/taxonomies/discover-sources", json={"name": "Hydrogen"}).json()
    assert (body["thematic_funds"], body[S3_FLAG]) == ([], True)


def test_fund_search_empty(client):  # AC-29
    client.use_search(Empty())
    r = client.post("/api/taxonomies/discover-sources", json={"name": "Hydrogen"})
    assert (r.status_code, r.json()[S3_FLAG]) == (200, False)


S4A = ("The news search could not be reached and no earnings-call transcripts were found for the selected universe, so "
       'there is nothing to draft from. Use another method, for example "Build from authority sources" with an uploaded '
       "document.")
S4B = ("No earnings-call transcripts were found for the selected universe and the news search is switched off, so there "
       'is nothing to draft from. Tick "Also search news", or use another method.')
S4C = ("The news search found nothing for this theme and no earnings-call transcripts were found for the selected "
       "universe, so there is nothing to draft from. Try another theme name, or use another method.")


@pytest.mark.parametrize(("search", "text"), [(Down(), S4A), (None, S4B), (Empty(), S4C)])
async def test_news_mining_says_why_there_is_nothing(fake_llm, search, text):  # AC-32, AC-33, AC-111
    with pytest.raises(ValueError) as exc:
        await build_theme_from_news_and_transcripts("Hydrogen", "d", fake_llm({}), search_client=search)
    assert str(exc.value) == text


def test_news_mining_route_answers_422(pg, client, monkeypatch):  # AC-32 through the API
    client.use_search(Down())
    monkeypatch.setattr(taxonomies_router, "get_llm_client", lambda: None)
    r = client.post("/api/taxonomies", json={"name": "Hydrogen", "description": "d",
                                             "derivation_method": "news_transcript_mining", "mine_news": True})
    assert (r.status_code, r.json()["detail"]) == (422, S4A)


async def test_news_down_but_transcripts_found(fake_llm, monkeypatch):  # AC-34
    from arp.research.taxonomy_sources import news_mining
    from arp.schemas.common import CompanyRef
    from arp.schemas.taxonomy_sources import CorpusSnippet, CorpusSourceType

    async def transcripts(companies, registry, keywords):
        return [CorpusSnippet(text="We build electrolysers.", source_type=CorpusSourceType.TRANSCRIPT, source_ref="c1:d1")]

    async def synth(theme_name, description, corpus, llm):
        from arp.llm.base import LLMUsage
        return [], "ok.", LLMUsage()

    monkeypatch.setattr(news_mining, "gather_corpus_from_transcripts", transcripts)
    monkeypatch.setattr(news_mining, "synthesize_activities_from_corpus", synth)
    _theme, notes, _ = await build_theme_from_news_and_transcripts(
        "Hydrogen", "d", fake_llm({}), search_client=Down(), companies=[CompanyRef(company_id="c1", name="Acme")],
        registry=object())
    assert "News search could not be reached; drafted from transcripts only." in notes


async def test_identity_run_unchanged_by_a_bot_challenge():  # AC-96
    class Edgar:
        async def search_by_name(self, name):
            return []

    transport = httpx.MockTransport(lambda request: httpx.Response(202, text="challenge"))
    signals = await gather_signals("Acme", edgar=Edgar(), search_client=DuckDuckGoSearchClient("t", transport=transport))
    assert (signals.search_results, signals.lookup_errors) == ([], [])


async def test_bot_challenge_is_a_failed_search():
    transport = httpx.MockTransport(lambda request: httpx.Response(202, text="challenge"))
    with pytest.raises(RuntimeError):
        await DuckDuckGoSearchClient("t", transport=transport).search("q")
