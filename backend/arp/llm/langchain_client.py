from __future__ import annotations

import base64
import hashlib
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
# request five times just burns quota before failing anyway. There is no
# longer a recoverable case to carve out: the one that existed -- a model
# rejecting an explicit `temperature` -- is gone now that `temperature` is
# never sent (see `_bind`), so a 400 here is unambiguously a bug to fix
# rather than a parameter to retry without.
_RETRYABLE = (APIStatusError, APITimeoutError, ConnectionError)
_NOT_RETRYABLE = (BadRequestError,)


def _droppable_list_indices(errors: list[dict]) -> dict[str, set[int]] | None:
    """Returns {field_name: {bad_indices}} if every validation error points
    into an item of a top-level list field -- safe to drop and re-validate
    without asking the model again. Returns None if any error touches
    something else (a missing/invalid required scalar field, a field that
    isn't a list, ...), which must never be silently patched.
    """
    droppable: dict[str, set[int]] = {}
    for err in errors:
        loc = err["loc"]
        if len(loc) < 2 or not isinstance(loc[0], str) or not isinstance(loc[1], int):
            return None
        droppable.setdefault(loc[0], set()).add(loc[1])
    return droppable


def _drop_invalid_list_items(output_model: type[T], raw_args: dict, exc: ValidationError) -> tuple[T | None, int]:
    """Best-effort recovery for a validation failure confined entirely to
    item(s) inside list fields -- the observed real-world failure mode
    (a malformed citation) -- so a single bad list entry doesn't force
    rejecting the whole structured response and a full model retry.
    Required/scalar fields (e.g. verdict, answer) are never patched this
    way: if any error touches one, this returns (None, 0) and the caller
    falls through to a normal retry with the model.
    """
    droppable = _droppable_list_indices(exc.errors())
    if not droppable:
        return None, 0
    corrected = dict(raw_args)
    dropped_count = 0
    for field, bad_indices in droppable.items():
        items = raw_args.get(field)
        if not isinstance(items, list):
            return None, 0
        corrected[field] = [item for i, item in enumerate(items) if i not in bad_indices]
        dropped_count += len(bad_indices)
    try:
        return output_model.model_validate(corrected), dropped_count
    except ValidationError:
        return None, 0


def _format_validation_errors(exc: ValidationError) -> str:
    """A per-field bullet list naming exactly what's wrong, instead of
    Pydantic's default str(exc) -- which for a large output model can dump
    the model's *entire* input back at itself (huge for a big list field)
    just to report one bad item, wasting tokens and burying the actual
    fields that need fixing."""
    lines = []
    for err in exc.errors():
        path = ".".join(str(p) for p in err["loc"]) or "(root)"
        got = repr(err.get("input"))
        if len(got) > 120:
            got = got[:117] + "..."
        lines.append(f"- `{path}`: {err['msg']} (got: {got})")
    return "\n".join(lines)


class LangChainAnthropicClient(LLMClient):
    """LLMClient backed by langchain-anthropic's ChatAnthropic.

    Structured output comes from offering exactly one tool whose input
    schema is the target Pydantic model's JSON schema, rather than trusting
    the model to emit clean JSON in prose. The tool is offered, not forced
    (`tool_choice: auto`): the current model generation rejects a forced
    `tool_choice` outright -- see `_bind` -- and the validation-retry loop
    re-prompts if a model answers in prose anyway, so a single advertised
    tool is enough without the 400.
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
        cache_refresh: bool = False,
        max_network_retries: int = 5,
        prompt_cache_enabled: bool = True,
    ) -> None:
        self._chat = ChatAnthropic(model=model, api_key=api_key, max_retries=0)
        self.model = model
        self.cache = DiskLLMCache(cache_dir, enabled=cache_enabled, refresh=cache_refresh)
        self._max_network_retries = max_network_retries
        self._prompt_cache_enabled = prompt_cache_enabled

    async def complete_structured(
        self,
        *,
        system: str,
        prompt: str,
        output_model: type[T],
        max_validation_retries: int = 2,
        temperature: float = 0.0,
        max_tokens: int = 8192,
        images: list[bytes] | None = None,
    ) -> tuple[T, LLMUsage]:
        schema = output_model.model_json_schema()
        prompt_version = hashlib.sha256(system.encode()).hexdigest()[:12]
        cache_key = self.cache.make_key(
            model=self.model,
            system=system,
            prompt=prompt,
            schema_name=output_model.__name__,
            schema_json=schema,
            temperature=temperature,
            image_hashes=[hashlib.sha256(b).hexdigest() for b in images] if images else None,
        )
        cached = self.cache.get(cache_key)
        if cached is not None:
            try:
                instance = output_model.model_validate(cached["result"])
                usage_fields = {**cached["usage"], "cached": True}
                usage_fields.setdefault("model", self.model)
                usage_fields.setdefault("prompt_version", prompt_version)
                usage_fields["provider"] = "anthropic"
                return instance, LLMUsage(**usage_fields)
            except ValidationError:
                pass  # cache entry stale/corrupt; fall through to a live call

        tool = {
            "name": _TOOL_NAME,
            "description": f"Emit the result as a {output_model.__name__} object matching the given schema exactly.",
            "input_schema": schema,
        }

        def _bind():
            # `temperature` is deliberately not sent. No model this codebase
            # targets accepts it any more: claude-sonnet-5, claude-opus-5 and
            # claude-opus-5-5 reject a non-default value with a 400, and
            # langchain-anthropic rejects it for claude-sonnet-5-5 client-side
            # with a ValueError. It used to be sent and then retried without
            # it on rejection, which meant *every* client instance burned one
            # round-trip on a request that could never succeed -- the retry
            # was silent, so this looked like it worked. These models fix
            # sampling internally, so dropping it changes nothing about
            # determinism; the disk cache is what makes a run reproducible.
            # The parameter stays in the signature: it is part of the
            # LLMClient contract and of the cache key, and a caller pointing
            # this at an older model that does accept it can reinstate the
            # bind here.
            extra = {"max_tokens": max_tokens}
            # tool_choice is "auto", not {"type": "tool"}: forcing a specific
            # tool is rejected outright by the current model generation
            # (`tool_choice: type "tool" and "any" are not supported for this
            # model` -- a 400 on claude-opus-5-5 and claude-sonnet-5-5), which
            # would fail every call site in this codebase at once the moment
            # ARP_LLM_MODEL is bumped. "auto" plus a single tool whose
            # description says to emit the result is enough in practice --
            # verified calling the tool on sonnet-5, opus-5, sonnet-5-5 and
            # opus-5-5 -- and the loop below still re-prompts if a model
            # answers in prose instead, so the guarantee does not rest on the
            # model's goodwill. Deliberately not `strict: True`: it would
            # require additionalProperties/required on every nested $def of
            # 60-odd Pydantic schemas, and the validation-retry loop below
            # already covers malformed arguments.
            return self._chat.bind_tools([tool], tool_choice={"type": "auto"}).bind(**extra)

        bound = _bind()

        system_content: str | list[dict] = system
        if self._prompt_cache_enabled and system:
            # Below the model's cacheable-prefix minimum this is a documented
            # no-op (no cache entry, no write premium) -- see _CACHE_CONTROL.
            system_content = [{"type": "text", "text": system, "cache_control": _CACHE_CONTROL}]

        human: str | list[dict] = prompt
        if images:
            human = [
                *({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(b).decode()}} for b in images),
                {"type": "text", "text": prompt},
            ]
        messages: list[BaseMessage] = [SystemMessage(content=system_content), HumanMessage(content=human)]
        total_input_tokens = 0
        total_output_tokens = 0
        total_cache_read_tokens = 0
        total_cache_creation_tokens = 0
        last_error: ValidationError | None = None

        for attempt in range(1, max_validation_retries + 2):
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
            except ValidationError as exc:
                instance, dropped = _drop_invalid_list_items(output_model, tool_call["args"], exc)
                if instance is None:
                    last_error = exc
                    messages.append(ai_message)
                    messages.append(
                        ToolMessage(
                            content=(
                                f"Your `{_TOOL_NAME}` call failed schema validation on these fields:\n"
                                f"{_format_validation_errors(exc)}\n\n"
                                f"Call `{_TOOL_NAME}` again with a corrected input that fixes every field listed "
                                f"above. Leave every other field exactly as it was."
                            ),
                            tool_call_id=tool_call["id"],
                            status="error",
                        )
                    )
                    continue
                if dropped:
                    logger.info(
                        "%s: dropped %d invalid list item(s) rather than requesting a full retry (%s)",
                        output_model.__name__,
                        dropped,
                        exc,
                    )

            usage = LLMUsage(
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cache_read_tokens=total_cache_read_tokens,
                cache_creation_tokens=total_cache_creation_tokens,
                attempts=attempt,
                model=self.model,
                prompt_version=prompt_version,
                provider="anthropic",
            )
            self.cache.set(
                cache_key,
                {"result": instance.model_dump(mode="json"), "usage": usage.model_dump(exclude={"cached"})},
            )
            return instance, usage

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
