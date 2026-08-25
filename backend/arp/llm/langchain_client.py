from __future__ import annotations

import logging
from pathlib import Path

from anthropic import APIStatusError, APITimeoutError, BadRequestError
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from arp.llm.base import LLMClient, LLMUsage, T
from arp.llm.cache import DiskLLMCache

logger = logging.getLogger(__name__)

_TOOL_NAME = "emit_result"

# Every agent in this codebase keeps `system` a fixed module-level constant
# per call site and puts all per-call variation (company, question,
# evidence) in `prompt` instead -- so the (system, tools) prefix is
# byte-identical across every call a given agent makes, the ideal shape for
# a cache breakpoint. Render order is tools -> system -> messages, and a
# breakpoint on the last system block caches both tools and system
# together, so one marker here is sufficient -- no separate tool tagging.
# 1h TTL: a single company's assessment run is 60+ sequential calls reusing
# the same prefix over several minutes, and a whole batch run reuses it
# across companies too -- well past the >=3-request break-even point for
# the 1h write premium (2x) vs. the 5m default (1.25x, 2-request break-even
# but a real risk of expiring mid-run on a slow pipeline).
_CACHE_CONTROL = {"type": "ephemeral", "ttl": "1h"}

# BadRequestError (400) is excluded even though it's an APIStatusError: a
# malformed-request rejection (e.g. an unsupported parameter) will never
# succeed on retry, so blindly backing off and re-sending the identical
# request five times just burns quota before failing anyway. The one
# recoverable case -- a model/account combination that rejects an
# explicit `temperature` -- is handled explicitly below, once per client
# instance, rather than through this generic transient-error retry.
_RETRYABLE = (APIStatusError, APITimeoutError, ConnectionError)
_NOT_RETRYABLE = (BadRequestError,)


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
        prompt_cache_enabled: bool = True,
    ) -> None:
        self._chat = ChatAnthropic(model=model, api_key=api_key, max_retries=0)
        self.model = model
        self.cache = DiskLLMCache(cache_dir, enabled=cache_enabled)
        self._max_network_retries = max_network_retries
        self._prompt_cache_enabled = prompt_cache_enabled
        # Set the first time this model/account combination rejects an
        # explicit `temperature` with a 400 ("temperature is deprecated
        # for this model") -- some model configurations fix temperature
        # internally and reject the field outright. Sticky per instance so
        # only the first call in a run pays for the failed attempt.
        self._temperature_unsupported = False

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

        def _bind(with_temperature: bool):
            extra = {"max_tokens": max_tokens}
            if with_temperature:
                extra["temperature"] = temperature
            return self._chat.bind_tools([tool], tool_choice={"type": "tool", "name": _TOOL_NAME}).bind(**extra)

        bound = _bind(with_temperature=not self._temperature_unsupported)

        system_content: str | list[dict] = system
        if self._prompt_cache_enabled and system:
            # Below the model's cacheable-prefix minimum this is a documented
            # no-op (no cache entry, no write premium) -- see _CACHE_CONTROL.
            system_content = [{"type": "text", "text": system, "cache_control": _CACHE_CONTROL}]

        messages: list[BaseMessage] = [SystemMessage(content=system_content), HumanMessage(content=prompt)]
        total_input_tokens = 0
        total_output_tokens = 0
        total_cache_read_tokens = 0
        total_cache_creation_tokens = 0
        last_error: ValidationError | None = None

        for attempt in range(1, max_validation_retries + 2):
            try:
                ai_message = await self._call_with_backoff(bound, messages)
            except BadRequestError as exc:
                if self._temperature_unsupported or "temperature" not in str(exc).lower():
                    raise
                # First-ever hit of this: remember it for every later call
                # on this client instance and retry once without it.
                self._temperature_unsupported = True
                bound = _bind(with_temperature=False)
                ai_message = await self._call_with_backoff(bound, messages)
            usage_meta = ai_message.usage_metadata or {}
            total_input_tokens += usage_meta.get("input_tokens", 0)
            total_output_tokens += usage_meta.get("output_tokens", 0)
            input_token_details = usage_meta.get("input_token_details") or {}
            total_cache_read_tokens += input_token_details.get("cache_read") or 0
            # langchain-anthropic reports the TTL-specific write count under
            # ephemeral_{5m,1h}_input_tokens and zeroes the generic
            # "cache_creation" key whenever it does -- sum all three rather
            # than reading "cache_creation" alone, which undercounts (reads
            # 0) for our 1h-TTL cache_control.
            total_cache_creation_tokens += (
                (input_token_details.get("cache_creation") or 0)
                + (input_token_details.get("ephemeral_5m_input_tokens") or 0)
                + (input_token_details.get("ephemeral_1h_input_tokens") or 0)
            )

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
                usage = LLMUsage(
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    cache_read_tokens=total_cache_read_tokens,
                    cache_creation_tokens=total_cache_creation_tokens,
                    attempts=attempt,
                )
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
            retry=retry_if_exception_type(_RETRYABLE) & retry_if_not_exception_type(_NOT_RETRYABLE),
        )
        async def _do_call() -> AIMessage:
            return await bound.ainvoke(messages)

        return await _do_call()
