from __future__ import annotations

import base64
import copy
import hashlib
import logging
from pathlib import Path

from anthropic import AsyncAnthropic
from anthropic.types import Message
from pydantic import ValidationError

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
# The 5-minute default TTL: every read refreshes it, and a pipeline run
# reuses each prefix seconds apart, so the 1h TTL's 2x write (vs 1.25x)
# bought nothing. Worth revisiting only if most calls come after 5-60
# minute pauses (Anthropic's rule of thumb: more than 1 call in 20).
_CACHE_CONTROL = {"type": "ephemeral"}

# Network retries are the SDK's own: exponential backoff on 408/409/429/5xx
# and connection errors/timeouts. A 400 (or any other 4xx) is never retried
# -- a malformed request won't succeed on a resend, it is a bug to fix.
# 4 retries = 5 attempts total, as before.
_MAX_NETWORK_RETRIES = 4


def _drop_paths(errors: list[dict]) -> set[tuple] | None:
    """The list elements to remove so the answer validates, as paths of names and indexes; None when any
    error must be retried instead. An error inside a citation drops that citation; an error at a list item
    (or its other sub-fields) drops the top-level item, except under a draft's `values` item, which is
    retried: a wrongly typed value, period_text or citations list must not silently lose a period."""
    paths: set[tuple] = set()
    for err in errors:
        loc = tuple(err["loc"])
        # the sub-field of each `values` item the error sits in: ("values", <int>, <field>)
        sub = [loc[i + 2] for i, p in enumerate(loc[:-2]) if p == "values" and isinstance(loc[i + 1], int)]
        if "value" in sub:
            return None
        cite = next((i for i, p in enumerate(loc) if isinstance(p, str) and p.endswith("citations")), None)
        if cite is not None:
            if len(loc) <= cite + 1 or not isinstance(loc[cite + 1], int):
                return None  # citations is not a list
            paths.add(loc[: cite + 2])
            continue
        if len(loc) < 2 or not isinstance(loc[0], str) or not isinstance(loc[1], int):
            return None
        if sub:
            return None
        paths.add(loc[:2])
    # a dropped item already takes its citations with it
    return {p for p in paths if not any(q != p and p[: len(q)] == q for q in paths)}


def _drop_invalid_list_items(output_model: type[T], raw_args: dict, exc: ValidationError) -> tuple[T | None, int]:
    """Best-effort recovery for a validation failure confined to list elements -- the observed real-world
    failure mode (a malformed citation) -- so one bad entry doesn't force rejecting the whole structured
    response and a full model retry. Anything else (a bad scalar, a wrongly typed period) returns (None, 0)
    and the caller retries with the model. Returns the model and the number of removed elements, and logs
    their paths at warning level.
    """
    paths = _drop_paths(exc.errors())
    if not paths:
        return None, 0
    corrected = copy.deepcopy(raw_args)
    removals: dict[int, tuple[list, set[int]]] = {}
    for path in paths:
        parent = corrected
        for step in path[:-1]:
            try:
                parent = parent[step]
            except (KeyError, IndexError, TypeError):
                return None, 0
        if not isinstance(parent, list) or not isinstance(path[-1], int) or path[-1] >= len(parent):
            return None, 0
        removals.setdefault(id(parent), (parent, set()))[1].add(path[-1])
    for items, bad in removals.values():
        items[:] = [item for i, item in enumerate(items) if i not in bad]
    try:
        instance = output_model.model_validate(corrected)
    except ValidationError:
        return None, 0
    logger.warning(
        "%s: dropped %d invalid list element(s) rather than requesting a full retry: %s",
        output_model.__name__,
        len(paths),
        ", ".join(sorted(".".join(map(str, p)) for p in paths)),
    )
    return instance, len(paths)


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
    """LLMClient backed by the `anthropic` SDK's AsyncAnthropic.

    Structured output comes from offering exactly one tool whose input
    schema is the target Pydantic model's JSON schema, rather than trusting
    the model to emit clean JSON in prose. The tool is offered, not forced
    (`tool_choice: auto`): the current model generation rejects a forced
    `tool_choice` outright -- see `_bind` -- and the validation-retry loop
    re-prompts if a model answers in prose anyway, so a single advertised
    tool is enough without the 400.
    Pydantic validation errors are fed back to the model as an `is_error`
    tool_result block for a bounded number of self-correction turns (a
    plain-text retry message after a tool_use turn is rejected by the API
    with a 400 -- it must be a matching tool_result block).
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        cache_dir: Path,
        cache_enabled: bool = True,
        cache_refresh: bool = False,
        prompt_cache_enabled: bool = True,
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key, max_retries=_MAX_NETWORK_RETRIES)
        self.model = model
        self.cache = DiskLLMCache(cache_dir, enabled=cache_enabled, refresh=cache_refresh)
        self._prompt_cache_enabled = prompt_cache_enabled

    async def _send(self, params: dict) -> Message:
        """One request; the seam a batch subclass overrides. `params` is plain JSON."""
        return await self._client.messages.create(**params)

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

        # `temperature` is deliberately not sent. No model this codebase
        # targets accepts it any more: claude-sonnet-5, claude-opus-5,
        # claude-opus-5-5 and claude-sonnet-5-5 reject a non-default value
        # with a 400. These models fix sampling internally, so dropping it
        # changes nothing about determinism; the disk cache is what makes a
        # run reproducible. The parameter stays in the signature: it is part
        # of the LLMClient contract and of the cache key.
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
        messages: list[dict] = [{"role": "user", "content": human}]
        total_input_tokens = 0
        total_output_tokens = 0
        total_cache_read_tokens = 0
        total_cache_creation_tokens = 0
        last_error: ValidationError | None = None

        for attempt in range(1, max_validation_retries + 2):
            sent = messages
            if self._prompt_cache_enabled and attempt > 1:
                # A retry resends the whole (often evidence-heavy) prompt. A
                # moving breakpoint on the newest block-list turn lets the next
                # retry read it from cache; copied so only that turn carries it
                # (max 4 breakpoints per request). Plain-string turns stay strings.
                i = next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i]["content"], list) and messages[i]["content"]), None)
                if i is not None:
                    blocks = messages[i]["content"]
                    marked = {**messages[i], "content": [*blocks[:-1], {**blocks[-1], "cache_control": _CACHE_CONTROL}]}
                    sent = [*messages[:i], marked, *messages[i + 1 :]]
            response = await self._send(
                {
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "system": system_content,
                    "messages": sent,
                    "tools": [tool],
                    "tool_choice": {"type": "auto"},
                }
            )
            u = response.usage
            # input_tokens is reported as the grand total (uncached + cache
            # read + cache write), which cost_tracker's base-input subtraction
            # assumes. The write count lives under
            # cache_creation.ephemeral_{5m,1h}_input_tokens and the
            # generic cache_creation_input_tokens can read 0 -- prefer the
            # TTL-specific sum, fall back to the generic field.
            cc = u.cache_creation
            cache_write = ((cc.ephemeral_5m_input_tokens or 0) + (cc.ephemeral_1h_input_tokens or 0) if cc else 0) or (
                u.cache_creation_input_tokens or 0
            )
            cache_read = u.cache_read_input_tokens or 0
            total_input_tokens += (u.input_tokens or 0) + cache_read + cache_write
            total_output_tokens += u.output_tokens or 0
            total_cache_read_tokens += cache_read
            total_cache_creation_tokens += cache_write

            tool_call = next((b for b in response.content if b.type == "tool_use" and b.name == _TOOL_NAME), None)
            if tool_call is None:
                last_error = ValidationError.from_exception_data(
                    output_model.__name__, [{"type": "missing", "loc": (), "input": None, "msg": "no tool call returned"}]
                )
                messages.append({"role": "assistant", "content": [b.model_dump(mode="json", exclude_none=True) for b in response.content]})
                messages.append({"role": "user", "content": f"You must respond by calling the `{_TOOL_NAME}` tool. Try again."})
                continue

            dropped = 0
            try:
                instance = output_model.model_validate(tool_call.input)
            except ValidationError as exc:
                instance, dropped = _drop_invalid_list_items(output_model, tool_call.input, exc)
                if instance is None:
                    last_error = exc
                    messages.append({"role": "assistant", "content": [b.model_dump(mode="json", exclude_none=True) for b in response.content]})
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_call.id,
                                    "is_error": True,
                                    "content": (
                                        f"Your `{_TOOL_NAME}` call failed schema validation on these fields:\n"
                                        f"{_format_validation_errors(exc)}\n\n"
                                        f"Call `{_TOOL_NAME}` again with a corrected input that fixes every field listed "
                                        f"above. Leave every other field exactly as it was."
                                    ),
                                }
                            ],
                        }
                    )
                    continue

            usage = LLMUsage(
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cache_read_tokens=total_cache_read_tokens,
                cache_creation_tokens=total_cache_creation_tokens,
                attempts=attempt,
                model=self.model,
                prompt_version=prompt_version,
                provider="anthropic",
                dropped_items=dropped,
            )
            self.cache.set(
                cache_key,
                {"result": instance.model_dump(mode="json"), "usage": usage.model_dump(exclude={"cached"})},
            )
            return instance, usage

        assert last_error is not None
        raise last_error
