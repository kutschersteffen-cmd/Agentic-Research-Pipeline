import types

from pydantic import BaseModel

from arp.llm import anthropic_client as anthropic_client_module
from arp.llm.anthropic_client import AnthropicLLMClient


class _Target(BaseModel):
    value: int


class _ToolUseBlock:
    type = "tool_use"

    def __init__(self, id, input):
        self.id = id
        self.input = input


class _FakeResponse:
    def __init__(self, content, input_tokens=10, output_tokens=5):
        self.content = content
        self.usage = types.SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)


class _FakeMessages:
    def __init__(self, responses):
        self._responses = responses
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses[len(self.calls) - 1]


class _FakeAsyncAnthropic:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


async def test_validation_failure_retry_sends_tool_result_not_plain_text(tmp_path, monkeypatch):
    """Anthropic's API requires that any assistant message containing a
    tool_use block be followed by a user message with a matching
    tool_result block (referencing the same tool_use_id) -- a plain-text
    follow-up user message is rejected outright with a 400. This is exactly
    what a real run against the live API surfaced: the schema-validation
    self-correction retry appended a bare string instead."""
    first_response = _FakeResponse([_ToolUseBlock("tu_1", {"wrong_field": 1})])
    second_response = _FakeResponse([_ToolUseBlock("tu_2", {"value": 42})])
    fake_client = _FakeAsyncAnthropic([first_response, second_response])

    monkeypatch.setattr(anthropic_client_module, "AsyncAnthropic", lambda api_key: fake_client)

    client = AnthropicLLMClient(api_key="test", model="test-model", cache_dir=tmp_path, cache_enabled=False)
    instance, usage = await client.complete_structured(system="sys", prompt="prompt", output_model=_Target)

    assert instance.value == 42
    assert usage.attempts == 2
    assert len(fake_client.messages.calls) == 2

    retry_message = fake_client.messages.calls[1]["messages"][-1]
    assert retry_message["role"] == "user"
    assert isinstance(retry_message["content"], list), "must be a tool_result block, not a plain string"
    tool_result = retry_message["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "tu_1"
    assert tool_result["is_error"] is True


async def test_no_tool_use_retry_can_stay_plain_text(tmp_path, monkeypatch):
    """When the model's response has no tool_use block at all (rare, given
    tool_choice is forced), there's no tool_use_id needing a tool_result --
    a plain-text nudge is valid in that case."""
    first_response = _FakeResponse([])  # no blocks at all -- model said nothing usable
    second_response = _FakeResponse([_ToolUseBlock("tu_1", {"value": 7})])
    fake_client = _FakeAsyncAnthropic([first_response, second_response])

    monkeypatch.setattr(anthropic_client_module, "AsyncAnthropic", lambda api_key: fake_client)

    client = AnthropicLLMClient(api_key="test", model="test-model", cache_dir=tmp_path, cache_enabled=False)
    instance, usage = await client.complete_structured(system="sys", prompt="prompt", output_model=_Target)

    assert instance.value == 7
    retry_message = fake_client.messages.calls[1]["messages"][-1]
    assert retry_message["role"] == "user"
    assert isinstance(retry_message["content"], str)


async def test_max_tokens_defaults_generously_and_is_overridable(tmp_path, monkeypatch):
    """A richer structured output (e.g. an expanded, many-field schema
    draft) can legitimately need more than a small hardcoded max_tokens --
    a live run against the real API hit exactly this: the response was cut
    off mid-JSON and failed validation with a required field entirely
    missing. max_tokens must default well above the old 4096 and remain
    overridable per call."""
    response = _FakeResponse([_ToolUseBlock("tu_1", {"value": 1})])
    fake_client = _FakeAsyncAnthropic([response])
    monkeypatch.setattr(anthropic_client_module, "AsyncAnthropic", lambda api_key: fake_client)
    client = AnthropicLLMClient(api_key="test", model="test-model", cache_dir=tmp_path, cache_enabled=False)

    await client.complete_structured(system="sys", prompt="prompt", output_model=_Target)
    assert fake_client.messages.calls[0]["max_tokens"] > 4096

    response2 = _FakeResponse([_ToolUseBlock("tu_2", {"value": 2})])
    fake_client2 = _FakeAsyncAnthropic([response2])
    monkeypatch.setattr(anthropic_client_module, "AsyncAnthropic", lambda api_key: fake_client2)
    client2 = AnthropicLLMClient(api_key="test", model="test-model", cache_dir=tmp_path, cache_enabled=False)
    await client2.complete_structured(system="sys", prompt="prompt", output_model=_Target, max_tokens=16000)
    assert fake_client2.messages.calls[0]["max_tokens"] == 16000
