from __future__ import annotations

import logging
from pathlib import Path

from anthropic import APIStatusError, APITimeoutError
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from arp.llm.base import LLMClient, LLMUsage, T
from arp.llm.cache import DiskLLMCache

logger = logging.getLogger(__name__)

_TOOL_NAME = "emit_result"

_RETRYABLE = (APIStatusError, APITimeoutError, ConnectionError)


class LangChainAnthropicClient(LLMClient):
    """LLMClient backed by langchain-anthropic's ChatAnthropic.

    Structured output is obtained the same way as before: forcing a single
    tool call whose input schema is the target Pydantic model's JSON
    schema, rather than trusting the model to emit clean JSON in prose.
    Pydantic validation errors are fed back to the model as a tool-result
    error for a bounded number of self-correction turns -- LangChain's
    message types (SystemMessage/HumanMessage/AIMessage/ToolMessage)
    translate to the exact same Anthropic wire format the raw-SDK
    implementation hand-built, verified against the same retry-message
    shape this codebase previously hit a real bug on (a plain-text retry
    message after a tool_use turn is rejected by the API with a 400 --
    it must be a matching tool_result block).

    langchain-anthropic's own retry (`max_retries` on ChatAnthropic) is
    disabled in favor of the explicit tenacity wrapper below, for the same
    exception-type control the previous implementation had.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        cache_dir: Path,
        cache_enabled: bool = True,
        max_network_retries: int = 5,
    ) -> None:
        self._chat = ChatAnthropic(model=model, api_key=api_key, max_retries=0)
        self.model = model
        self.cache = DiskLLMCache(cache_dir, enabled=cache_enabled)
        self._max_network_retries = max_network_retries

    async def complete_structured(
        self,
        *,
        system: str,
        prompt: str,
        output_model: type[T],
        max_validation_retries: int = 2,
        temperature: float = 0.0,
        max_tokens: int = 8192,
    ) -> tuple[T, LLMUsage]:
        schema = output_model.model_json_schema()
        cache_key = self.cache.make_key(
            model=self.model,
            system=system,
            prompt=prompt,
            schema_name=output_model.__name__,
            schema_json=schema,
            temperature=temperature,
        )
        cached = self.cache.get(cache_key)
        if cached is not None:
            try:
                instance = output_model.model_validate(cached["result"])
                return instance, LLMUsage(**{**cached["usage"], "cached": True})
            except ValidationError:
                pass  # cache entry stale/corrupt; fall through to a live call

        tool = {
            "name": _TOOL_NAME,
            "description": f"Emit the result as a {output_model.__name__} object matching the given schema exactly.",
            "input_schema": schema,
        }
        bound = self._chat.bind_tools([tool], tool_choice={"type": "tool", "name": _TOOL_NAME}).bind(
            max_tokens=max_tokens, temperature=temperature
        )

        messages: list[BaseMessage] = [SystemMessage(content=system), HumanMessage(content=prompt)]
        total_input_tokens = 0
        total_output_tokens = 0
        last_error: ValidationError | None = None

        for attempt in range(1, max_validation_retries + 2):
            ai_message = await self._call_with_backoff(bound, messages)
            usage_meta = ai_message.usage_metadata or {}
            total_input_tokens += usage_meta.get("input_tokens", 0)
            total_output_tokens += usage_meta.get("output_tokens", 0)

            tool_call = next((tc for tc in ai_message.tool_calls if tc["name"] == _TOOL_NAME), None)
            if tool_call is None:
                last_error = ValidationError.from_exception_data(
                    output_model.__name__, [{"type": "missing", "loc": (), "input": None, "msg": "no tool call returned"}]
                )
                messages.append(ai_message)
                messages.append(HumanMessage(content=f"You must respond by calling the `{_TOOL_NAME}` tool. Try again."))
                continue

            try:
                instance = output_model.model_validate(tool_call["args"])
                usage = LLMUsage(input_tokens=total_input_tokens, output_tokens=total_output_tokens, attempts=attempt)
                self.cache.set(
                    cache_key,
                    {"result": instance.model_dump(mode="json"), "usage": usage.model_dump(exclude={"cached"})},
                )
                return instance, usage
            except ValidationError as exc:
                last_error = exc
                messages.append(ai_message)
                messages.append(
                    ToolMessage(
                        content=(
                            f"Your `{_TOOL_NAME}` call failed schema validation with these errors:\n"
                            f"{exc}\n\nCall `{_TOOL_NAME}` again with a corrected input that fixes every error."
                        ),
                        tool_call_id=tool_call["id"],
                        status="error",
                    )
                )

        assert last_error is not None
        raise last_error

    async def _call_with_backoff(self, bound, messages: list[BaseMessage]) -> AIMessage:
        @retry(
            reraise=True,
            stop=stop_after_attempt(self._max_network_retries),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            retry=retry_if_exception_type(_RETRYABLE),
        )
        async def _do_call() -> AIMessage:
            return await bound.ainvoke(messages)

        return await _do_call()
