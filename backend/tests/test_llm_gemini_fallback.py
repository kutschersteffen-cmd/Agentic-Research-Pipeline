"""Spec llm-gemini-fallback: Gemini serves when Anthropic has no key, or after a credit/auth error. Fake clients only."""
import logging
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from arp.api import deps
from arp.api.auth import current_user
from arp.api.main import runtime_error_handler
from arp.api.routers import authority_taxonomy
from arp.config import Settings
from arp.llm.base import LLMUsage
from arp.llm.batching_client import BatchingLLMClient
from arp.llm.factory import batch_settings, build_llm_client, build_verifier_llm_client
from arp.llm.gemini_client import GeminiClient
from arp.llm.langchain_client import LangChainAnthropicClient
from tests.conftest import PRINCIPAL
from tests.test_langchain_client_retry import _message

ANT, GEM = "sk-ant-test-key", "g-test-key"
LOGGER = "arp.llm.fallback_client"
NO_ANTHROPIC = "ARP_ANTHROPIC_API_KEY is not set. Provide an Anthropic API key via environment variable or a .env file before running any agent pipeline."
CREDIT = "Your credit balance is too low to access the Anthropic API."


class Answer(BaseModel):
    value: int


def _resp(status, message):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx.Response(status, request=req, json={"error": {"message": message}})


def _err(cls, status, message=CREDIT):
    return cls(message, response=_resp(status, message), body=None)


def credit_error():
    return _err(anthropic.BadRequestError, 400)


def settings(tmp_path, anthropic_key=ANT, gemini_key=GEM, **kw):
    kw.setdefault("llm_cache_enabled", False)
    return Settings(anthropic_api_key=anthropic_key, gemini_api_key=gemini_key, cache_dir=tmp_path, **kw)


@pytest.fixture
def fakes(monkeypatch):
    """`fakes.ant` / `fakes.gem` count the requests each fake received; set `fakes.ant_error` to make Anthropic raise."""
    f = SimpleNamespace(ant=0, gem=0, ant_error=None, gem_error=None)

    async def ant_send(self, params):
        f.ant += 1
        if f.ant_error:
            raise f.ant_error
        return _message("tu", {"value": 1})

    async def gem_send(self, contents, config):
        f.gem += 1
        if f.gem_error:
            raise f.gem_error
        return SimpleNamespace(text='{"value": 2}', usage_metadata=None)

    monkeypatch.setattr(LangChainAnthropicClient, "_send", ant_send)
    monkeypatch.setattr(BatchingLLMClient, "_send", ant_send)
    monkeypatch.setattr(GeminiClient, "_send", gem_send)
    return f


async def call(client):
    return await client.complete_structured(system="s", prompt="p", output_model=Answer)


def warnings(caplog):
    return [r for r in caplog.records if r.levelno == logging.WARNING and r.name == LOGGER]


def gemini_only(tmp_path, **kw):
    return settings(tmp_path, anthropic_key=None, **kw)


# --- no Anthropic key, Gemini key (AC-1..3, 21..23, 28, 30) ---

async def test_ac1_no_anthropic_key_builds_gemini(tmp_path, fakes):
    client = build_llm_client(gemini_only(tmp_path))
    assert isinstance(client, GeminiClient)
    out, usage = await call(client)
    assert (fakes.gem, usage.provider, usage.model, usage.fallback_from) == (1, "google", "gemini-3.8-flash", "claude-sonnet-5-5")
    assert out.value == 2


async def test_ac2_fallback_model_setting(tmp_path, fakes):
    _, usage = await call(build_llm_client(gemini_only(tmp_path, gemini_fallback_model="gemini-3.8-pro")))
    assert (usage.model, usage.fallback_from) == ("gemini-3.8-pro", "claude-sonnet-5-5")


def test_ac3_build_warns_once(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    build_llm_client(gemini_only(tmp_path))
    [rec] = warnings(caplog)
    assert "claude-sonnet-5-5" in rec.getMessage() and "gemini-3.8-flash" in rec.getMessage()


def test_ac4_no_key_runtime_error(tmp_path):
    with pytest.raises(RuntimeError) as e:
        build_llm_client(settings(tmp_path, anthropic_key=None, gemini_key=None))
    assert str(e.value) == NO_ANTHROPIC


def test_ac5_api_returns_503(tmp_path, monkeypatch):
    monkeypatch.setattr(deps, "get_settings", lambda: settings(tmp_path, anthropic_key=None, gemini_key=None))
    app = FastAPI()
    app.include_router(authority_taxonomy.router)
    app.add_exception_handler(RuntimeError, runtime_error_handler)
    app.dependency_overrides.update({current_user: lambda: PRINCIPAL, deps.get_run_store: lambda: None, deps.get_web_search_client: lambda: None})
    res = TestClient(app).post("/api/authority-taxonomy/runs", json={"theme_name": "t"})
    assert (res.status_code, res.json()["detail"]) == (503, NO_ANTHROPIC)


async def test_ac21_verifier_on_gemini(tmp_path, fakes):
    _, usage = await call(build_verifier_llm_client(gemini_only(tmp_path)))
    assert (usage.model, usage.fallback_from) == ("gemini-3.8-flash", "claude-opus-5-5")


async def test_ac22_distinct_verifier_model_no_independence_warning(tmp_path, fakes, caplog):
    caplog.set_level(logging.DEBUG)
    _, usage = await call(build_verifier_llm_client(gemini_only(tmp_path, gemini_fallback_verifier_model="gemini-3.8-pro")))
    assert usage.model == "gemini-3.8-pro"
    assert not any("verifier independence" in r.getMessage() for r in warnings(caplog))


def test_ac23_equal_models_warn_about_independence(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    build_verifier_llm_client(gemini_only(tmp_path))
    [rec] = warnings(caplog)
    assert "verifier independence" in rec.getMessage()


async def test_ac28_batch_run_uses_plain_gemini(tmp_path, fakes):
    client = build_llm_client(batch_settings(gemini_only(tmp_path), True))
    assert isinstance(client, GeminiClient) and not isinstance(client, BatchingLLMClient)
    _, usage = await call(client)
    assert (usage.batch, usage.fallback_from) == (False, "claude-sonnet-5-5")


async def test_ac30_model_override_is_replaced(tmp_path, fakes):
    _, usage = await call(build_llm_client(gemini_only(tmp_path), model="claude-haiku-5-5"))
    assert (usage.model, usage.fallback_from) == ("gemini-3.8-flash", "claude-haiku-5-5")


# --- both keys, nothing wrong (AC-6, 7) ---

async def test_ac6_both_keys_anthropic_serves(tmp_path, fakes, caplog):
    caplog.set_level(logging.DEBUG)
    _, usage = await call(build_llm_client(settings(tmp_path)))
    assert (fakes.ant, fakes.gem, usage.provider, usage.fallback_from) == (1, 0, "anthropic", "")
    assert not warnings(caplog)


async def test_ac7_verifier_stays_on_anthropic(tmp_path, fakes, caplog):
    caplog.set_level(logging.DEBUG)
    _, usage = await call(build_verifier_llm_client(settings(tmp_path)))
    assert (usage.provider, usage.model, usage.fallback_from) == ("anthropic", "claude-opus-5-5", "")
    assert not warnings(caplog)


async def test_ac8_anthropic_only_no_fallback(tmp_path, fakes):
    fakes.ant_error = credit_error()
    client = build_llm_client(settings(tmp_path, gemini_key=None))
    assert isinstance(client, LangChainAnthropicClient)
    with pytest.raises(anthropic.BadRequestError):
        await call(client)
    assert fakes.gem == 0


# --- credit/auth errors fall back (AC-9..17) ---

async def _fell_back(tmp_path, fakes, error):
    fakes.ant_error = error
    out, usage = await call(build_llm_client(settings(tmp_path)))
    assert (fakes.ant, fakes.gem, out.value) == (1, 1, 2)
    assert (usage.provider, usage.model, usage.fallback_from) == ("google", "gemini-3.8-flash", "claude-sonnet-5-5")


async def test_ac9_credit_error_falls_back(tmp_path, fakes):
    await _fell_back(tmp_path, fakes, credit_error())


async def test_ac10_401_falls_back(tmp_path, fakes):
    await _fell_back(tmp_path, fakes, _err(anthropic.AuthenticationError, 401, "invalid x-api-key"))


async def test_ac11_403_falls_back(tmp_path, fakes):
    await _fell_back(tmp_path, fakes, _err(anthropic.PermissionDeniedError, 403, "forbidden"))


async def test_ac12_credit_match_is_case_insensitive(tmp_path, fakes):
    await _fell_back(tmp_path, fakes, _err(anthropic.BadRequestError, 400, "Credit Balance too low"))


async def test_ac13_later_calls_stay_on_gemini(tmp_path, fakes):
    fakes.ant_error = credit_error()
    client = build_llm_client(settings(tmp_path))
    await call(client)
    _, usage = await call(client)
    assert (fakes.ant, fakes.gem, usage.fallback_from) == (1, 2, "claude-sonnet-5-5")


async def test_ac14_ac15_one_warning_per_client(tmp_path, fakes, caplog):
    caplog.set_level(logging.DEBUG)
    fakes.ant_error = credit_error()
    client = build_llm_client(settings(tmp_path))
    await call(client)
    [rec] = warnings(caplog)
    assert "claude-sonnet-5-5" in rec.getMessage() and "gemini-3.8-flash" in rec.getMessage()
    await call(client)
    assert len(warnings(caplog)) == 1


async def test_ac16_no_key_in_any_output(tmp_path, fakes, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    fakes.ant_error = credit_error()
    await call(build_llm_client(settings(tmp_path)))
    build_llm_client(gemini_only(tmp_path))
    out = capsys.readouterr()
    text = caplog.text + out.out + out.err + " ".join(r.getMessage() for r in caplog.records)
    assert ANT not in text and GEM not in text


async def test_ac17_gemini_error_propagates(tmp_path, fakes):
    fakes.ant_error, fakes.gem_error = credit_error(), RuntimeError("gemini down")
    with pytest.raises(RuntimeError, match="gemini down"):
        await call(build_llm_client(settings(tmp_path)))
    assert (fakes.ant, fakes.gem) == (1, 1)


# --- other errors do not fall back (AC-18..20) ---

@pytest.mark.parametrize("error", [
    _err(anthropic.RateLimitError, 429, "slow down"),
    _err(anthropic.InternalServerError, 529, "overloaded"),
    _err(anthropic.BadRequestError, 400, "max_tokens too large"),
])
async def test_ac18_19_20_other_errors_propagate(tmp_path, fakes, caplog, error):
    caplog.set_level(logging.DEBUG)
    fakes.ant_error = error
    with pytest.raises(type(error)):
        await call(build_llm_client(settings(tmp_path)))
    assert fakes.gem == 0 and not warnings(caplog)


# --- verifier independence after a runtime fallback (AC-24, 25) ---

async def test_ac24_verifier_runtime_fallback_warns(tmp_path, fakes, caplog):
    caplog.set_level(logging.DEBUG)
    fakes.ant_error = credit_error()
    _, usage = await call(build_verifier_llm_client(settings(tmp_path)))
    assert (usage.model, usage.fallback_from) == ("gemini-3.8-flash", "claude-opus-5-5")
    [rec] = warnings(caplog)
    assert "verifier independence" in rec.getMessage()


async def test_ac25_distinct_models_no_independence_warning(tmp_path, fakes, caplog):
    caplog.set_level(logging.DEBUG)
    fakes.ant_error = credit_error()
    await call(build_verifier_llm_client(settings(tmp_path, gemini_fallback_verifier_model="gemini-3.8-pro")))
    [rec] = warnings(caplog)
    assert "verifier independence" not in rec.getMessage()


# --- explicit gemini model, batch, cache, stand-ins (AC-26..33) ---

async def test_ac26_explicit_gemini_model_unmarked(tmp_path, fakes, caplog):
    caplog.set_level(logging.DEBUG)
    _, usage = await call(build_llm_client(gemini_only(tmp_path, llm_model="gemini-3.8-flash")))
    assert usage.fallback_from == "" and not warnings(caplog)


def test_ac27_explicit_gemini_model_needs_key(tmp_path):
    with pytest.raises(RuntimeError) as e:
        build_llm_client(settings(tmp_path, gemini_key=None, llm_model="gemini-3.8-flash"))
    assert str(e.value) == "ARP_GEMINI_API_KEY is not set, and the run uses the Gemini model gemini-3.8-flash."


async def test_ac29_batch_credit_error_falls_back_unbatched(tmp_path, fakes):
    fakes.ant_error = credit_error()
    client = build_llm_client(batch_settings(settings(tmp_path), True))
    _, usage = await call(client)
    assert (fakes.ant, fakes.gem, usage.batch, usage.provider, usage.fallback_from) == (1, 1, False, "google", "claude-sonnet-5-5")


async def test_ac31_providers_do_not_share_cache_entries(tmp_path, fakes):
    s = settings(tmp_path, llm_cache_enabled=True)
    await call(build_llm_client(s))
    _, usage = await call(build_llm_client(gemini_only(tmp_path, llm_cache_enabled=True)))
    assert (fakes.ant, fakes.gem, usage.cached) == (1, 1, False)


async def test_ac32_cached_hit_keeps_fallback_from(tmp_path, fakes):
    client = build_llm_client(gemini_only(tmp_path, llm_cache_enabled=True))
    await call(client)
    _, usage = await call(client)
    assert (fakes.gem, usage.cached, usage.fallback_from) == (1, True, "claude-sonnet-5-5")


async def test_ac33_standins_bypass_everything(tmp_path, fakes):
    from arp.standins import StandInLLMClient

    standins = tmp_path / "standins"
    standins.mkdir()
    client = build_llm_client(Settings(standins_dir=standins, cache_dir=tmp_path, anthropic_api_key=None, gemini_api_key=None))
    assert isinstance(client, StandInLLMClient)
    assert (fakes.ant, fakes.gem) == (0, 0)


# --- settings and usage (AC-34..37) ---

def test_ac34_35_default_models():
    s = Settings()
    assert (s.gemini_fallback_model, s.gemini_fallback_verifier_model) == ("gemini-3.8-flash", "gemini-3.8-flash")


def test_ac36_37_usage_field():
    assert LLMUsage().fallback_from == ""
    d = LLMUsage(model="m").model_dump()
    d.pop("fallback_from")
    assert LLMUsage.model_validate(d).fallback_from == ""
