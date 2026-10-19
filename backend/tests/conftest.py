from __future__ import annotations

import os

import pytest

from arp.api.auth import Principal

PRINCIPAL = Principal(user_id="u_test", name="Test", role="approver")


@pytest.fixture(autouse=True)
def _disable_hybrid_retrieval_by_default(monkeypatch):
    """Settings.hybrid_retrieval_enabled defaults to True in production
    (see arp/config.py), but that path downloads a ~220MB embedding model
    from HuggingFace on first use -- exactly the kind of network
    dependency this suite is designed to never need (see README: "pytest
    -q # unit tests, no API key/network required"). Any test that
    specifically wants to exercise hybrid retrieval should construct its
    own Settings(hybrid_retrieval_enabled=True, ...) (an explicit
    constructor kwarg overrides this env var) and mock embed_texts, rather
    than relying on the real network call.
    """
    monkeypatch.setenv("ARP_HYBRID_RETRIEVAL_ENABLED", "false")


@pytest.fixture(autouse=True)
def _disable_rerank_by_default(monkeypatch):
    """Settings.rerank_enabled is opt-in, and the cross-encoder
    downloads a model on first use -- same no-network rule as hybrid
    retrieval above. Tests of reranking patch `arp.retrieval.rerank._score`."""
    monkeypatch.setenv("ARP_RERANK_ENABLED", "false")


@pytest.fixture(autouse=True)
def _no_remote_compute(monkeypatch):
    """A developer's backend/.env may name the Cloud Run compute services
    (arp/compute/); tests never send work there. Tests of the cloud path
    patch arp.compute.client.get_settings."""
    monkeypatch.setenv("ARP_COMPUTE_PARSE_URL", "")
    monkeypatch.setenv("ARP_COMPUTE_MODELS_URL", "")


@pytest.fixture(autouse=True)
def _review_quality_dir_in_tmp(monkeypatch, tmp_path):
    """A confirmed correction appends to settings.review_quality_dir; never the repo's data/ in tests."""
    monkeypatch.setenv("ARP_REVIEW_QUALITY_DIR", str(tmp_path / "review_quality"))


@pytest.fixture(autouse=True)
def _identity_lookups_offline(monkeypatch):
    """execute_identity_run turns on the GLEIF/Wikidata/site lookups; a test that passes no transport
    gets one that refuses every request, so the lookups degrade to the no-hit path instead of the network."""
    import httpx

    from arp.discovery import identity_pipeline

    real = identity_pipeline.resolve_company_identity

    def refuse(request):
        raise httpx.ConnectError("network disabled in tests", request=request)

    async def offline(company, *, transport=None, **kwargs):
        return await real(company, transport=transport or httpx.MockTransport(refuse), **kwargs)

    monkeypatch.setattr(identity_pipeline, "resolve_company_identity", offline)


@pytest.fixture(autouse=True)
def _barrier_sources_offline(monkeypatch):
    """A derivation with the refresh flag on fetches its registered sources; unless a test serves them
    with `transition_barrier_helpers.fetch_stub`, it fetches nothing, so no request leaves the test."""
    from arp.transition_barrier import fetching

    async def nothing(sources, today):
        return []

    monkeypatch.setattr(fetching, "fetch_sources", nothing)


@pytest.fixture(scope="session")
def _pg_schema():
    dsn = os.environ.get("ARP_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.fail("ARP_TEST_POSTGRES_DSN is required: docker compose up -d postgres", pytrace=False)
    from arp.storage.postgres_schema import ensure_schema

    ensure_schema(dsn)
    return dsn


@pytest.fixture
def pg(_pg_schema, monkeypatch, tmp_path):
    """Empty tables for each test; yields the DSN, which is also the settings DSN (ARP_POSTGRES_DSN).
    Set through monkeypatch so a test's own setenv/delenv of it unwinds in the right order."""
    from arp.config import get_settings
    from tests.postgres_helpers import reset_postgres_tables

    reset_postgres_tables(_pg_schema)
    monkeypatch.setenv("ARP_POSTGRES_DSN", _pg_schema)
    monkeypatch.setenv("ARP_BLOB_STORE_DIR", str(tmp_path / "blobs"))  # provider payloads, never the repo's data/
    get_settings.cache_clear()
    yield _pg_schema
    get_settings.cache_clear()


@pytest.fixture
def run_store(pg, tmp_path):
    from arp.db.runs import RunStore

    return RunStore(pg, tmp_path / "runs")


class FakeLLMClient:
    """Deterministic stand-in for LLMClient in tests: returns pre-scripted
    responses keyed by the requested output_model's class name, in order.
    No network, no API key needed.
    """

    def __init__(self, script: dict[str, list]) -> None:
        self._script = {k: list(v) for k, v in script.items()}
        self.calls: list[str] = []
        self.prompts: list[str] = []
        self.images: list[list[bytes] | None] = []

    async def complete_structured(self, *, system, prompt, output_model, max_validation_retries=2, temperature=0.0, max_tokens=8192, images=None):
        from arp.llm.base import LLMUsage

        name = output_model.__name__
        self.calls.append(name)
        self.prompts.append(prompt)
        self.images.append(images)
        queue = self._script.get(name)
        if not queue:
            raise AssertionError(f"FakeLLMClient has no scripted response left for {name}")
        return queue.pop(0), LLMUsage(input_tokens=10, output_tokens=10, provider="fake")


@pytest.fixture
def fake_llm():
    return FakeLLMClient


class FakeSearchClient:
    """Deterministic stand-in for WebSearchClient: returns pre-scripted
    results per query substring match, in order added. No network."""

    def __init__(self, results_by_query_substring: dict[str, list]) -> None:
        self._results = results_by_query_substring
        self.queries: list[str] = []

    async def search(self, query: str, max_results: int = 5):
        self.queries.append(query)
        for substring, results in self._results.items():
            if substring in query:
                return results[:max_results]
        return []


@pytest.fixture
def fake_search():
    return FakeSearchClient


@pytest.fixture(autouse=True)
def _signed_in_approver():
    """Every router now sits behind arp.api.auth.authorize; existing API tests
    exercise endpoint behaviour, not sign-in, so they run as an approver.
    tests/test_auth.py clears these overrides to test the real thing."""
    from arp.api.auth import authorize, current_user
    from arp.api.main import app

    principal = PRINCIPAL
    app.dependency_overrides[authorize] = lambda: principal
    app.dependency_overrides[current_user] = lambda: principal
    yield
    app.dependency_overrides.pop(authorize, None)
    app.dependency_overrides.pop(current_user, None)


@pytest.fixture
def sample_house_universe(tmp_path, monkeypatch):
    """The house stewardship program on the synthetic sample (it defaults to the portfolio holdings)."""
    from arp.config import get_settings
    from arp.stewardship.universe import HouseUniverseSetting

    monkeypatch.setenv("ARP_STEWARDSHIP_STREAMS_DIR", str(tmp_path / "house_universe_streams"))
    get_settings.cache_clear()
    HouseUniverseSetting(get_settings().stewardship_streams_dir).set("sample", "tests")
    yield
    get_settings.cache_clear()


@pytest.fixture
def neo4j_graph(monkeypatch):
    """An empty company graph (ARP_TEST_NEO4J_URI); fails without one, like Postgres. Also sets
    ARP_NEO4J_* so the app and CLI under test use the same graph; yields a driver."""
    from neo4j import GraphDatabase

    from arp.config import get_settings

    uri = os.environ.get("ARP_TEST_NEO4J_URI")
    if not uri:
        pytest.fail("ARP_TEST_NEO4J_URI is required: bash .claude/hooks/ensure-deps.sh neo4j", pytrace=False)
    user = os.environ.get("ARP_TEST_NEO4J_USER", "neo4j")
    password = os.environ.get("ARP_TEST_NEO4J_PASSWORD", "arp_neo4j_test")
    monkeypatch.setenv("ARP_NEO4J_URI", uri)
    monkeypatch.setenv("ARP_NEO4J_USER", user)
    monkeypatch.setenv("ARP_NEO4J_PASSWORD", password)
    get_settings.cache_clear()
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        driver.execute_query("MATCH (n) DETACH DELETE n")
        yield driver
    get_settings.cache_clear()
