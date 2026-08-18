from anthropic.types import Message, ToolUseBlock, Usage
from pydantic import BaseModel

from arp.llm.langchain_client import LangChainAnthropicClient


class _Target(BaseModel):
    value: int


def _message(tool_id: str, tool_input: dict, input_tokens: int = 10, output_tokens: int = 5) -> Message:
    return Message(
        id="msg_1",
        type="message",
        role="assistant",
        model="claude-sonnet-5",
        content=[ToolUseBlock(type="tool_use", id=tool_id, name="emit_result", input=tool_input)],
        stop_reason="tool_use",
        stop_sequence=None,
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class _FakeMessages:
    def __init__(self, responses: list[Message]) -> None:
        self._responses = responses
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses[len(self.calls) - 1]


class _FakeAsyncClient:
    def __init__(self, responses: list[Message]) -> None:
        self.messages = _FakeMessages(responses)


def _client_with_responses(tmp_path, responses: list[Message]) -> tuple[LangChainAnthropicClient, _FakeAsyncClient]:
    client = LangChainAnthropicClient(api_key="test", model="test-model", cache_dir=tmp_path, cache_enabled=False)
    fake = _FakeAsyncClient(responses)
    client._chat._async_client = fake  # override the lazy anthropic.AsyncClient with our fake
    return client, fake


async def test_validation_failure_retry_sends_tool_result_not_plain_text(tmp_path):
    """Anthropic's API requires that any assistant message containing a
    tool_use block be followed by a user message with a matching
    tool_result block (referencing the same tool_use_id) -- a plain-text
    follow-up user message is rejected outright with a 400. This is the
    same real bug the previous raw-SDK implementation hit; confirming
    langchain-anthropic's ToolMessage(status="error") still serializes to
    the correct tool_result shape."""
    first_response = _message("tu_1", {"wrong_field": 1})
    second_response = _message("tu_2", {"value": 42})
    client, fake = _client_with_responses(tmp_path, [first_response, second_response])

    instance, usage = await client.complete_structured(system="sys", prompt="prompt", output_model=_Target)

    assert instance.value == 42
    assert usage.attempts == 2
    assert len(fake.messages.calls) == 2

    retry_message = fake.messages.calls[1]["messages"][-1]
    assert retry_message["role"] == "user"
    assert isinstance(retry_message["content"], list), "must be a tool_result block, not a plain string"
    tool_result = retry_message["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "tu_1"
    assert tool_result["is_error"] is True


async def test_no_tool_use_retry_can_stay_plain_text(tmp_path):
    """When the model's response has no matching tool call at all (rare,
    given tool_choice is forced), there's no tool_use_id needing a
    tool_result -- a plain-text nudge is valid in that case."""
    first_response = _message("tu_1", {"value": 1})
    first_response.content = []  # no blocks at all -- model said nothing usable
    second_response = _message("tu_2", {"value": 7})
    client, fake = _client_with_responses(tmp_path, [first_response, second_response])

    instance, usage = await client.complete_structured(system="sys", prompt="prompt", output_model=_Target)

    assert instance.value == 7
    retry_message = fake.messages.calls[1]["messages"][-1]
    assert retry_message["role"] == "user"
    assert isinstance(retry_message["content"], str)


async def test_max_tokens_defaults_generously_and_is_overridable(tmp_path):
    """A richer structured output (e.g. an expanded, many-field schema
    draft) can legitimately need more than a small hardcoded max_tokens --
    max_tokens must default well above the old 4096 and remain overridable
    per call."""
    client, fake = _client_with_responses(tmp_path, [_message("tu_1", {"value": 1})])
    await client.complete_structured(system="sys", prompt="prompt", output_model=_Target)
    assert fake.messages.calls[0]["max_tokens"] > 4096

    client2, fake2 = _client_with_responses(tmp_path, [_message("tu_2", {"value": 2})])
    await client2.complete_structured(system="sys", prompt="prompt", output_model=_Target, max_tokens=16000)
    assert fake2.messages.calls[0]["max_tokens"] == 16000


async def test_temperature_is_actually_sent_to_the_model(tmp_path):
    """The previous raw-SDK implementation declared `temperature` on its
    signature but never forwarded it to the API call at all -- confirm the
    new client actually wires it through."""
    client, fake = _client_with_responses(tmp_path, [_message("tu_1", {"value": 1})])
    await client.complete_structured(system="sys", prompt="prompt", output_model=_Target, temperature=0.3)
    assert fake.messages.calls[0]["temperature"] == 0.3
