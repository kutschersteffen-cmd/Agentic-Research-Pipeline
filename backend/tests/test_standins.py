from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from arp import standins
from arp.api import deps
from arp.config import Settings
from arp.llm.factory import batch_settings, build_llm_client, build_verifier_llm_client
from arp.llm.gemini_client import GeminiClient
from arp.llm.langchain_client import LangChainAnthropicClient
from arp.research.taxonomy_sources.fetch import fetch_source_original, fetch_source_text

BACKEND = Path(__file__).resolve().parents[1]


class X(BaseModel):
    answer: str


def _settings(folder: Path, **kw) -> Settings:
    return Settings(standins_dir=folder, anthropic_api_key=None, gemini_api_key=None, cache_dir=folder / "cache", **kw)


@pytest.fixture
def on(tmp_path, monkeypatch) -> Path:
    settings = _settings(tmp_path)
    monkeypatch.setattr(standins, "get_settings", lambda: settings)
    deps.get_web_search_client.cache_clear()
    yield tmp_path
    deps.get_web_search_client.cache_clear()


def _write(folder: Path, name: str, data) -> None:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))


def _calls(folder: Path) -> list[dict]:
    return [json.loads(line) for line in (folder / "calls.jsonl").read_text().splitlines()]


def test_guard_refuses_a_model_key(tmp_path):
    for key in ("anthropic_api_key", "gemini_api_key"):
        with pytest.raises(ValidationError, match="ARP_STANDINS_DIR is set together with a model API key; stand-ins are for tests only. Unset one of them."):
            Settings(standins_dir=tmp_path, **{"anthropic_api_key": None, "gemini_api_key": None, key: "x"})


def test_guard_refuses_a_missing_dir(tmp_path):
    with pytest.raises(ValidationError, match=f"ARP_STANDINS_DIR {tmp_path / 'nope'} is not a directory."):
        Settings(standins_dir=tmp_path / "nope", anthropic_api_key=None, gemini_api_key=None)


async def test_every_factory_client_answers_from_the_fixture(on):  # AC-13
    _write(on, "model/X.json", {"output": {"answer": "42"}})
    for model in ("claude-sonnet-5-5", "gemini-2.5-pro"):
        for batch in (False, True):
            s = batch_settings(_settings(on, llm_model=model, llm_verifier_model=model), batch)
            for client in (build_llm_client(s), build_verifier_llm_client(s)):
                out, usage = await client.complete_structured(system="s", prompt="p", output_model=X)
                assert out == X(answer="42")
                assert (usage.provider, usage.model, usage.input_tokens, usage.output_tokens) == ("stand-in", "stand-in", 0, 0)
    assert _calls(on)[0] == {"kind": "model", "name": "X", "system": "s", "prompt": "p"}


@pytest.mark.parametrize(
    "content, message",
    [
        (None, "no stand-in for X"),  # AC-14
        ({"error": "down"}, "down"),  # AC-28
        ("{not json", "stand-in model/X.json is not valid JSON"),  # AC-29
    ],
)
async def test_model_failures(on, content, message):
    if content is not None:
        _write(on, "model/X.json", content)
    with pytest.raises(RuntimeError) as exc:
        await build_llm_client(_settings(on)).complete_structured(system="s", prompt="p", output_model=X)
    assert str(exc.value) == message


async def test_model_output_that_does_not_match(on):  # AC-30
    _write(on, "model/X.json", {"output": {}})
    with pytest.raises(RuntimeError) as exc:
        await build_llm_client(_settings(on)).complete_structured(system="s", prompt="p", output_model=X)
    assert str(exc.value).startswith("stand-in model/X.json does not match X:")


async def test_delays(on):  # AC-31
    _write(on, "model/X.json", {"output": {"answer": "a"}, "delay_seconds": 1})
    _write(on, "fetch.json", {"https://a.example/1": {"text": "t", "delay_seconds": 1}})
    start = time.monotonic()
    await build_llm_client(_settings(on)).complete_structured(system="s", prompt="p", output_model=X)
    assert time.monotonic() - start >= 1
    start = time.monotonic()
    assert await fetch_source_text("https://a.example/1", "ua") == "t"
    assert time.monotonic() - start >= 1


async def test_fetch_text(on, monkeypatch):  # AC-15
    def no_http(*a, **kw):
        raise AssertionError("HTTP request sent")

    monkeypatch.setattr(httpx.AsyncClient, "send", no_http)
    long = "w" * 70_000
    _write(on, "fetch.json", {"https://u.example": {"text": ""}, "https://v.example": {"error": "e"}, "https://w.example": {"text": long}})
    got = [await fetch_source_text(u, "ua") for u in ("https://u.example", "https://v.example", "https://w.example", "https://x.example")]
    assert got == [None, None, long[:60_000], None]
    assert [c["url"] for c in _calls(on)] == ["https://u.example", "https://v.example", "https://w.example", "https://x.example"]


async def test_fetch_original_skips_ssrf_guard_and_cache(on):
    _write(on, "fetch.json", {"http://127.0.0.1:9/x": {"text": "local"}})
    cache = on / "originals"
    assert await fetch_source_original("http://127.0.0.1:9/x", "ua", cache) == (b"local", "text/plain")
    assert await fetch_source_original("http://127.0.0.1:9/y", "ua", cache) is None
    assert not cache.exists() or not any(cache.iterdir())


async def test_search(on):  # AC-16
    results = [{"title": "t0", "url": "https://r.example/0"}] + [
        {"title": f"t{i}", "url": f"https://r.example/{i}", "snippet": "s"} for i in range(1, 14)
    ]
    _write(on, "search.json", {"results": results})
    got = await deps.get_web_search_client().search("q", max_results=5)
    assert [r.url for r in got] == [r["url"] for r in results]
    assert got[0].snippet == ""
    assert _calls(on) == [{"kind": "search", "query": "q"}]


async def test_search_failures(on):
    client = deps.get_web_search_client()
    with pytest.raises(RuntimeError, match="^no stand-in for web search$"):
        await client.search("q")
    _write(on, "search.json", {"error": "down"})
    with pytest.raises(RuntimeError, match="^down$"):
        await client.search("q")


async def test_concurrent_calls_log_whole_lines(on):  # AC-32
    _write(on, "search.json", {"results": []})
    client = deps.get_web_search_client()
    await asyncio.gather(*(asyncio.to_thread(asyncio.run, client.search("q" * 5000)) for _ in range(50)))
    assert len(_calls(on)) == 50


def test_ddg_constructed_only_by_the_factory():  # AC-33
    out = subprocess.run(["grep", "-rln", "DuckDuckGoSearchClient(", "arp"], cwd=BACKEND, capture_output=True, text=True).stdout.split()
    assert out == ["arp/discovery/site_finder.py"]


def test_switch_off_keeps_the_real_clients(tmp_path):  # AC-18
    for model, cls in (("claude-sonnet-5-5", LangChainAnthropicClient), ("gemini-2.5-pro", GeminiClient)):
        s = Settings(llm_model=model, anthropic_api_key="k", gemini_api_key="k", cache_dir=tmp_path)
        assert type(build_llm_client(s)) is cls
    with pytest.raises(RuntimeError, match="ARP_ANTHROPIC_API_KEY is not set"):
        build_llm_client(Settings(anthropic_api_key=None, cache_dir=tmp_path))


async def test_switch_off_keeps_the_ssrf_guard(monkeypatch):  # AC-19
    monkeypatch.delenv("ARP_STANDINS_DIR", raising=False)
    monkeypatch.setattr(standins, "active_dir", lambda: None)
    assert await fetch_source_text("http://127.0.0.1/x", "ua") is None
