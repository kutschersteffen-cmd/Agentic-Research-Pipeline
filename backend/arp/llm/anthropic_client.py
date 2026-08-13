from __future__ import annotations

import logging
from pathlib import Path

from anthropic import AsyncAnthropic, APIStatusError, APITimeoutError
from pydantic import BaseModel, ValidationError
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


class AnthropicLLMClient(LLMClient):
    """LLMClient backed by the Anthropic Messages API.

    Structured output is obtained by forcing a single tool call whose input
    schema is the target Pydantic model's JSON schema, rather than trusting
    the model to emit clean JSON in prose. Pydantic validation errors are
    fed back to the model for a bounded number of self-correction turns.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        cache_dir: Path,
        cache_enabled: bool = True,
        max_network_retries: int = 5,
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
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
    ) -> tuple[T, LLMUsage]:
        schema = output_model.model_json_schema()
        cache_key = self.cache.make_key(
            model=self.model, system=system, prompt=prompt, schema_name=output_model.__name__, schema_json=schema
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

        messages: list[dict] = [{"role": "user", "content": prompt}]
        total_input_tokens = 0
        total_output_tokens = 0
        last_error: ValidationError | None = None

        for attempt in range(1, max_validation_retries + 2):
            response = await self._call_with_backoff(system=system, messages=messages, tool=tool)
            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            tool_use = next((b for b in response.content if b.type == "tool_use"), None)
            if tool_use is None:
                last_error = ValidationError.from_exception_data(
                    output_model.__name__, [{"type": "missing", "loc": (), "input": None, "msg": "no tool_use block returned"}]
                )
                messages.append({"role": "assistant", "content": response.content})
                messages.append(
                    {"role": "user", "content": f"You must respond by calling the `{_TOOL_NAME}` tool. Try again."}
                )
                continue

            try:
                instance = output_model.model_validate(tool_use.input)
                usage = LLMUsage(input_tokens=total_input_tokens, output_tokens=total_output_tokens, attempts=attempt)
                self.cache.set(
                    cache_key,
                    {"result": instance.model_dump(mode="json"), "usage": usage.model_dump(exclude={"cached"})},
                )
                return instance, usage
            except ValidationError as exc:
                last_error = exc
                messages.append({"role": "assistant", "content": response.content})
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use.id,
                                "is_error": True,
                                "content": (
                                    f"Your `{_TOOL_NAME}` call failed schema validation with these errors:\n"
                                    f"{exc}\n\nCall `{_TOOL_NAME}` again with a corrected input that fixes every error."
                                ),
                            }
                        ],
                    }
                )

        assert last_error is not None
        raise last_error

    async def _call_with_backoff(self, *, system: str, messages: list[dict], tool: dict):
        @retry(
            reraise=True,
            stop=stop_after_attempt(self._max_network_retries),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            retry=retry_if_exception_type(_RETRYABLE),
        )
        async def _do_call():
            return await self._client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system,
                messages=messages,
                tools=[tool],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
            )

        return await _do_call()
