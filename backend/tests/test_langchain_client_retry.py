import httpx
from anthropic import BadRequestError
from anthropic.types import Message, ToolUseBlock, Usage
from pydantic import BaseModel

from arp.llm.langchain_client import LangChainAnthropicClient


class _Target(BaseModel):
    value: int


class _Item(BaseModel):
    kind: str


class _TargetWithItems(BaseModel):
    value: int
    items: list[_Item] = []


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


def _bad_request(message: str) -> BadRequestError:
    response = httpx.Response(status_code=400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    return BadRequestError(message, response=response, body=None)


async def test_temperature_unsupported_model_falls_back_and_sticks(tmp_path):
    """Some model/account combinations reject an explicit `temperature`
    outright ("temperature is deprecated for this model") -- a real error
    hit against the live API. The client must recover by retrying once
    without temperature, then skip sending it on every later call on this
    same instance rather than repeating the failed attempt each time."""

    class _FlakyMessages(_FakeMessages):
        def __init__(self, responses: list[Message]) -> None:
            super().__init__(responses)
            self._served = 0

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            if "temperature" in kwargs:
                raise _bad_request("`temperature` is deprecated for this model.")
            response = self._responses[self._served]
            self._served += 1
            return response

    client = LangChainAnthropicClient(api_key="test", model="test-model", cache_dir=tmp_path, cache_enabled=False)
    fake = _FakeAsyncClient([_message("tu_1", {"value": 1})])
    fake.messages = _FlakyMessages([_message("tu_1", {"value": 1})])
    client._chat._async_client = fake

    instance, _usage = await client.complete_structured(system="sys", prompt="prompt", output_model=_Target)
    assert instance.value == 1
    assert client._temperature_unsupported is True
    # One failed attempt (with temperature) + one successful retry (without).
    assert len(fake.messages.calls) == 2
    assert "temperature" in fake.messages.calls[0]
    assert "temperature" not in fake.messages.calls[1]

    # A second call on the same client instance must not repeat the failed attempt.
    fake.messages._responses.append(_message("tu_2", {"value": 2}))
    instance2, _usage2 = await client.complete_structured(system="sys", prompt="prompt2", output_model=_Target)
    assert instance2.value == 2
    assert len(fake.messages.calls) == 3
    assert "temperature" not in fake.messages.calls[2]


async def test_system_prompt_gets_cache_control_by_default(tmp_path):
    """Every agent's system prompt is a fixed constant per call site, so it's
    the ideal cache breakpoint -- tagged on by default."""
    client, fake = _client_with_responses(tmp_path, [_message("tu_1", {"value": 1})])
    await client.complete_structured(system="a stable persona prompt", prompt="prompt", output_model=_Target)

    sent_system = fake.messages.calls[0]["system"]
    assert isinstance(sent_system, list)
    assert sent_system[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert sent_system[0]["text"] == "a stable persona prompt"


async def test_prompt_cache_can_be_disabled(tmp_path):
    client = LangChainAnthropicClient(
        api_key="test", model="test-model", cache_dir=tmp_path, cache_enabled=False, prompt_cache_enabled=False
    )
    fake = _FakeAsyncClient([_message("tu_1", {"value": 1})])
    client._chat._async_client = fake

    await client.complete_structured(system="a stable persona prompt", prompt="prompt", output_model=_Target)

    assert fake.messages.calls[0]["system"] == "a stable persona prompt"


async def test_cache_read_and_creation_tokens_are_captured(tmp_path):
    """Anthropic's raw `usage.input_tokens` is the uncached remainder only
    (per the API's own accounting) -- langchain-anthropic adds cache_read +
    cache_creation on top to report a grand total, which is what
    cost_tracker.estimate_cost_usd's base_input_tokens subtraction assumes."""
    client, fake = _client_with_responses(tmp_path, [_message("tu_1", {"value": 1})])
    fake.messages._responses[0].usage = Usage(
        input_tokens=1200, output_tokens=5, cache_read_input_tokens=1000, cache_creation_input_tokens=0
    )

    _instance, usage = await client.complete_structured(system="sys", prompt="prompt", output_model=_Target)

    assert usage.input_tokens == 2200  # 1200 uncached + 1000 cache_read
    assert usage.cache_read_tokens == 1000
    assert usage.cache_creation_tokens == 0


async def test_cache_creation_tokens_captured_under_1h_ttl(tmp_path):
    """With ttl="1h" (what this client always sends), Anthropic reports the
    write count under cache_creation.ephemeral_1h_input_tokens and
    langchain-anthropic zeroes the generic cache_creation_input_tokens field
    when it does -- extraction must sum both, not just the generic field
    (a real bug this test would have caught)."""
    from anthropic.types.usage import CacheCreation

    client, fake = _client_with_responses(tmp_path, [_message("tu_1", {"value": 1})])
    fake.messages._responses[0].usage = Usage(
        input_tokens=18,
        output_tokens=5,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
        cache_creation=CacheCreation(ephemeral_1h_input_tokens=5003, ephemeral_5m_input_tokens=0),
    )

    _instance, usage = await client.complete_structured(system="sys", prompt="prompt", output_model=_Target)

    assert usage.cache_creation_tokens == 5003
    assert usage.input_tokens == 18 + 5003


async def test_bad_list_item_is_dropped_without_a_retry(tmp_path):
    """A single malformed item inside a list field (the real failure mode
    observed in production -- a malformed citation) shouldn't force
    rejecting the whole structured response and a full model retry: the
    bad item is dropped and the rest of the response is accepted as-is."""
    client, fake = _client_with_responses(
        tmp_path,
        [_message("tu_1", {"value": 1, "items": [{"kind": "a"}, {"not_kind": "b"}]})],
    )
    instance, usage = await client.complete_structured(system="sys", prompt="prompt", output_model=_TargetWithItems)

    assert len(fake.messages.calls) == 1  # no retry needed
    assert usage.attempts == 1
    assert instance.value == 1
    assert [i.kind for i in instance.items] == ["a"]  # the malformed second item was dropped, not the whole draft


async def test_bad_required_field_is_never_silently_dropped(tmp_path):
    """List-item tolerance must not extend to a required scalar field --
    that always forces a real retry with the model, never a silent patch."""
    first_response = _message("tu_1", {"items": [{"kind": "a"}]})  # missing required `value`
    second_response = _message("tu_2", {"value": 7, "items": [{"kind": "a"}]})
    client, fake = _client_with_responses(tmp_path, [first_response, second_response])

    instance, usage = await client.complete_structured(system="sys", prompt="prompt", output_model=_TargetWithItems)

    assert len(fake.messages.calls) == 2
    assert usage.attempts == 2
    assert instance.value == 7


async def test_retry_message_names_the_exact_failing_field(tmp_path):
    """The retry message should point at the specific field that failed,
    not dump Pydantic's default str(exc) (which can echo the model's
    entire input back at it for one bad field)."""
    first_response = _message("tu_1", {"items": [{"kind": "a"}]})  # missing required `value`
    second_response = _message("tu_2", {"value": 7, "items": [{"kind": "a"}]})
    client, fake = _client_with_responses(tmp_path, [first_response, second_response])

    await client.complete_structured(system="sys", prompt="prompt", output_model=_TargetWithItems)

    retry_message = fake.messages.calls[1]["messages"][-1]
    tool_result_text = retry_message["content"][0]["content"]
    assert "`value`" in tool_result_text
    assert "Field required" in tool_result_text


async def test_unrelated_bad_request_is_not_swallowed(tmp_path):
    """A 400 unrelated to temperature (e.g. a genuinely malformed request)
    must still propagate, not be silently retried as if it were the
    temperature-unsupported case."""

    class _AlwaysBadRequest(_FakeMessages):
        async def create(self, **kwargs):
            self.calls.append(kwargs)
            raise _bad_request("Some other malformed-request error.")

    client = LangChainAnthropicClient(api_key="test", model="test-model", cache_dir=tmp_path, cache_enabled=False)
    fake = _FakeAsyncClient([])
    fake.messages = _AlwaysBadRequest([])
    client._chat._async_client = fake

    try:
        await client.complete_structured(system="sys", prompt="prompt", output_model=_Target)
        raise AssertionError("expected BadRequestError to propagate")
    except BadRequestError:
        pass
    # No blind backoff retries against a non-transient, non-temperature 400.
    assert len(fake.messages.calls) == 1
