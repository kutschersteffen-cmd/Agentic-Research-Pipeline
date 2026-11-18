"""showcase-stewardship-fixes AC-7..AC-18: a failed EDGAR or web-search lookup is recorded, never fatal."""

import httpx
import pytest

from arp.api.routers.identity import get_identity_results
from arp.config import Settings
from arp.discovery.identity_agents import _format_signals, gather_signals
from arp.discovery.identity_pipeline import run_identity_resolution
from arp.discovery.site_finder import SearchResult
from arp.orchestration.batch_runner import run_batch, run_sinks
from arp.schemas.common import CompanyRef
from arp.schemas.discovery import GleifMatch, IdentityAdjudication, IdentitySignals, IdentityVerdict
from arp.storage.run_store import RunStore

GLEIF = GleifMatch(lei="5299000ACMEPOWER1065", legal_name="Acme AG", country="DE")
HIT = SearchResult(title="Acme IR", url="https://acme.example.com/ir", snippet="IR")


class _Edgar:
    def __init__(self, exc=None):
        self.exc = exc

    async def search_by_name(self, name, limit=5):
        if self.exc:
            raise self.exc
        return []


class _Search:
    def __init__(self, exc=None, hits=()):
        self.exc, self.hits = exc, list(hits)

    async def search(self, query, max_results=5):
        if self.exc:
            raise self.exc
        return self.hits


@pytest.fixture
def gleif(monkeypatch):
    async def one(client, name, limit=5):
        return [GLEIF]

    monkeypatch.setattr("arp.discovery.identity_agents.name_matches", one)
    return object()  # any client: name_matches is stubbed


async def test_web_search_failure_is_recorded_and_gleif_still_asked(gleif):  # AC-7, AC-8
    s = await gather_signals("Acme", edgar=_Edgar(), search_client=_Search(httpx.ConnectTimeout("")), gleif_client=gleif)
    assert (s.gleif_matches, s.search_results) == ([GLEIF], [])
    assert s.lookup_errors == ["web search: ConnectTimeout"]


async def test_edgar_failure_is_recorded_and_the_rest_still_asked(gleif):  # AC-9, AC-10
    s = await gather_signals("Acme", edgar=_Edgar(httpx.ConnectError("boom")), search_client=_Search(hits=[HIT]),
                             gleif_client=gleif)
    assert s.edgar_matches == [] and s.lookup_errors == ["EDGAR: ConnectError: boom"]
    assert [h.url for h in s.search_results] == [HIT.url] and s.gleif_matches == [GLEIF]


async def test_both_failures_recorded_in_order(gleif):  # AC-11
    s = await gather_signals("Acme", edgar=_Edgar(httpx.ConnectError("boom")),
                             search_client=_Search(httpx.ConnectTimeout("")), gleif_client=gleif)
    assert s.lookup_errors == ["EDGAR: ConnectError: boom", "web search: ConnectTimeout"]
    assert s.gleif_matches == [GLEIF]


async def test_prompt_says_not_available_for_a_failed_search(gleif):  # AC-12, AC-13
    s = await gather_signals("Acme", edgar=_Edgar(), search_client=_Search(httpx.ConnectTimeout("")), gleif_client=gleif)
    prompt = _format_signals(s)
    assert "Web search results: not available (ConnectTimeout)" in prompt.splitlines()
    assert "Web search results: none found" not in prompt
    assert "Web search results: none found" in _format_signals(IdentitySignals())


async def test_no_errors_when_lookups_succeed(gleif):  # AC-14
    s = await gather_signals("Acme", edgar=_Edgar(), search_client=_Search(hits=[HIT]), gleif_client=gleif)
    assert s.lookup_errors == []


def test_older_stored_signals_load():  # AC-15
    assert IdentitySignals.model_validate({"edgar_matches": [], "search_results": []}).lookup_errors == []


async def test_identity_results_api_carries_lookup_errors(tmp_path, fake_llm, pg, gleif):  # AC-16
    settings = Settings(anthropic_api_key="unused", runs_dir=tmp_path / "runs", identifier_map_path=tmp_path / "idmap.jsonl",
                        documents_dir=tmp_path / "docs", cache_dir=tmp_path / "cache", discovery_state_dir=tmp_path / "disc")
    store = RunStore(pg, settings.runs_dir)
    llm = fake_llm({IdentityAdjudication.__name__: [IdentityAdjudication(
        verdict=IdentityVerdict.UNRESOLVED, confidence=0.1, rationale="Nothing found.")]})
    run_id = await run_identity_resolution([CompanyRef(company_id="acme", name="Acme")], llm=llm, settings=settings,
                                           run_store=store, edgar=_Edgar(), search_client=_Search(httpx.ConnectTimeout("")))
    [row] = get_identity_results(run_id, run_store=store)["results"]
    assert row["signals"]["lookup_errors"] == ["web search: ConnectTimeout"]


@pytest.mark.parametrize(("exc", "error"), [(httpx.ReadTimeout(""), "ReadTimeout"), (RuntimeError("boom"), "boom")])
async def test_batch_error_row_is_never_empty(tmp_path, pg, exc, error):  # AC-17, AC-18
    store = RunStore(pg, tmp_path)

    async def worker(item):
        raise exc

    await run_batch(["a"], item_key=lambda i: i, worker=worker, sinks=run_sinks(store, "r"), concurrency=1,
                    result_to_json=lambda r: {"value": r})
    assert [r["error"] for r in store.read_errors("r")] == [error]


def test_a_result_with_a_failed_lookup_is_rechecked():  # review finding: --previous-run retries a failed lookup
    from arp.discovery.match_rules import needs_recheck
    from arp.schemas.discovery import IdentityResolutionResult

    company = CompanyRef(company_id="x", name="Acme Corp")

    def result(errors):
        return IdentityResolutionResult(company_id="x", input_name="Acme Corp", verdict=IdentityVerdict.UNCERTAIN,
                                        confidence=0.3, rationale="r", match_rule="ambiguous",
                                        signals=IdentitySignals(lookup_errors=errors))

    assert needs_recheck(result(["EDGAR: ConnectError: boom", "web search: ConnectTimeout"]), company, None) is True
    assert needs_recheck(result([]), company, None) is False  # unchanged without a failed lookup
