from __future__ import annotations

import pytest


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


class FakeLLMClient:
    """Deterministic stand-in for LLMClient in tests: returns pre-scripted
    responses keyed by the requested output_model's class name, in order.
    No network, no API key needed.
    """

    def __init__(self, script: dict[str, list]) -> None:
        self._script = {k: list(v) for k, v in script.items()}
        self.calls: list[str] = []
        self.prompts: list[str] = []

    async def complete_structured(self, *, system, prompt, output_model, max_validation_retries=2, temperature=0.0):
        from arp.llm.base import LLMUsage

        name = output_model.__name__
        self.calls.append(name)
        self.prompts.append(prompt)
        queue = self._script.get(name)
        if not queue:
            raise AssertionError(f"FakeLLMClient has no scripted response left for {name}")
        return queue.pop(0), LLMUsage(input_tokens=10, output_tokens=10)


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
