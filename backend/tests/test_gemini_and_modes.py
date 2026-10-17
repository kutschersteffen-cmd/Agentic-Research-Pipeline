from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

from arp.config import Settings
from arp.extraction.steps import MODES, StepSettings, pipeline_shape
from arp.llm.base import LLMUsage
from arp.llm.factory import build_llm_client
from arp.llm.gemini_client import GeminiClient
from arp.llm.langchain_client import LangChainAnthropicClient
from arp.orchestration.cost_tracker import estimate_cost_usd


class Answer(BaseModel):
    value: int


def _response(text: str, prompt=100, out=20, thoughts=5, cached=0):
    usage = SimpleNamespace(prompt_token_count=prompt, candidates_token_count=out, thoughts_token_count=thoughts,
                            cached_content_token_count=cached)
    return SimpleNamespace(text=text, usage_metadata=usage)


class _Scripted(GeminiClient):
    def __init__(self, tmp_path, replies):
        super().__init__(api_key="k", model="gemini-3.8-flash", cache_dir=tmp_path)
        self.replies, self.sent = list(replies), []

    async def _send(self, contents, config):
        self.sent.append((list(contents), config))
        return self.replies.pop(0)


async def test_a_valid_json_answer_is_validated_and_its_usage_reported(tmp_path):
    client = _Scripted(tmp_path, [_response('{"value": 7}', cached=4096)])
    out, usage = await client.complete_structured(system="sys", prompt="p", output_model=Answer, images=[b"\x89PNG"])
    assert out == Answer(value=7)
    assert (usage.input_tokens, usage.output_tokens, usage.cache_read_tokens) == (100, 25, 4096)  # thinking billed as output
    assert (usage.provider, usage.model, usage.attempts) == ("google", "gemini-3.8-flash", 1)
    [(contents, config)] = client.sent
    assert config.system_instruction == "sys" and config.response_mime_type == "application/json"
    assert config.response_json_schema == Answer.model_json_schema()
    assert [p.inline_data is not None for p in contents[0].parts] == [True, False]  # the image comes before the prompt


async def test_invalid_json_is_sent_back_with_its_errors_then_retried(tmp_path):
    client = _Scripted(tmp_path, [_response('{"value": "x"}'), _response("not json"), _response('{"value": 3}')])
    out, usage = await client.complete_structured(system="s", prompt="p", output_model=Answer)
    assert (out.value, usage.attempts, usage.input_tokens) == (3, 3, 300)
    retry = client.sent[1][0][-1].parts[0].text
    assert "failed schema validation" in retry and "value" in retry


async def test_retries_run_out_with_the_last_validation_error(tmp_path):
    client = _Scripted(tmp_path, [_response('{"value": "x"}')] * 2)
    with pytest.raises(ValidationError):
        await client.complete_structured(system="s", prompt="p", output_model=Answer, max_validation_retries=1)


async def test_a_repeated_call_comes_from_the_disk_cache_at_no_cost(tmp_path):
    client = _Scripted(tmp_path, [_response('{"value": 7}')])
    await client.complete_structured(system="s", prompt="p", output_model=Answer)
    out, usage = await client.complete_structured(system="s", prompt="p", output_model=Answer)
    assert out.value == 7 and usage.cached and len(client.sent) == 1
    assert estimate_cost_usd("gemini-3.8-flash", usage) == 0.0


def test_gemini_models_route_to_the_gemini_client(tmp_path):
    s = Settings(anthropic_api_key="a", gemini_api_key="g", cache_dir=tmp_path)
    assert isinstance(build_llm_client(s, model="gemini-4-argon"), GeminiClient)
    assert isinstance(build_llm_client(s, model="claude-sonnet-5-5"), LangChainAnthropicClient)
    batch = s.model_copy(update={"llm_batch": True})
    assert isinstance(build_llm_client(batch, model="gemini-3.8-flash"), GeminiClient)  # no Gemini batch client: plain calls
    no_anthropic = Settings(anthropic_api_key=None, gemini_api_key="g", cache_dir=tmp_path)
    assert isinstance(build_llm_client(no_anthropic, model="gemini-3.8-flash"), GeminiClient)
    with pytest.raises(RuntimeError, match="ARP_GEMINI_API_KEY"):
        build_llm_client(Settings(anthropic_api_key="a", gemini_api_key=None, cache_dir=tmp_path), model="gemini-4-argon")


def test_gemini_prices():
    one_m = LLMUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert estimate_cost_usd("gemini-3.8-flash", one_m) == pytest.approx(4.5)
    assert estimate_cost_usd("gemini-4-argon", one_m.model_copy(update={"cache_read_tokens": 500_000})) == pytest.approx(11.05)


def test_modes_keep_extractor_and_verifier_apart_and_normal_is_the_default():
    for name, mode in MODES.items():
        assert mode.llm_model != mode.llm_verifier_model, name
    effective = StepSettings.effective(Settings())
    assert all(getattr(effective, k) == v for k, v in MODES["normal"].model_dump(exclude_none=True).items())
    assert pipeline_shape("custom", Settings())["modes"]["cheap"]["llm_model"] == "gemini-3.8-flash"


async def test_a_run_mode_applies_and_step_settings_override_it(monkeypatch):
    from arp.api.routers import extraction

    seen = {}

    async def fake_dispatch(req, settings, *a):
        seen["settings"] = settings
        return {}

    monkeypatch.setattr(extraction, "_dispatch", fake_dispatch)
    req = extraction.StartRequest(profile="custom", mode="max", step_settings=StepSettings(evidence_max_chunks=5))
    await extraction.start_extraction(req, Settings(), None, None, None, None)
    s = seen["settings"]
    assert (s.llm_model, s.llm_verifier_model, s.vision_fallback_enabled) == ("claude-opus-5-5", "gemini-4-argon", True)
    assert s.evidence_max_chunks == 5  # the editor's own setting wins over the mode
