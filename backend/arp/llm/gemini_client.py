"""LLMClient backed by Google's `google-genai` SDK, for `gemini-*` models.

Same contract as LangChainAnthropicClient: a schema-validated `output_model` instance, a bounded
validation-retry loop that shows the model its errors, SDK-level retries for transient errors, PNG
images ahead of the prompt, and the shared disk cache (keys include the model id, so Claude and Gemini
entries never collide). Structured output uses Gemini's JSON mode with the model's full JSON schema.

Caching: Gemini caches a shared request prefix of at least 4,096 tokens on its own (implicit caching);
the cached share comes back as `cached_content_token_count` and is reported as cache_read_tokens.
Explicit cache objects are not used (Gemini 4 Argon does not support them). Batch: no Gemini batch
client yet, so a batch run sends Gemini calls one by one (see llm/factory.py).

Thinking shares max_output_tokens with the answer. An answer cut off there (finish_reason MAX_TOKENS) is
resent with double the limit, up to _MAX_OUTPUT_CAP, instead of being treated as bad JSON; an answer the
API blocked raises at once. A schema Gemini rejects as too complex ("too many states") is sent again relaxed
(constraints dropped, every property required), then as plain JSON mode with the schema in the system prompt;
Pydantic validates the answer either way, and the level that worked is remembered per output model.
Extraction calls think at a low level; verifier clients keep the model default."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from google import genai
from google.genai import errors, types
from pydantic import ValidationError
from pydantic_core import PydanticCustomError

from arp.llm.base import LLMClient, LLMUsage, T
from arp.llm.cache import DiskLLMCache
from arp.llm.langchain_client import _MAX_NETWORK_RETRIES, _drop_invalid_list_items, _format_validation_errors

_MAX_OUTPUT_CAP = 65_536


_CONSTRAINTS = ("maxItems", "minItems", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "pattern",
                "format", "default", "title")


def _relaxed(node):
    """A copy of a JSON schema without the constraints that blow up Gemini's decoder, every property required."""
    if isinstance(node, list):
        return [_relaxed(n) for n in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k in _CONSTRAINTS:
            continue
        if k in ("properties", "$defs"):
            out[k] = {name: _relaxed(sub) for name, sub in v.items()}
        else:
            out[k] = _relaxed(v)
    if isinstance(out.get("properties"), dict):
        out["required"] = list(out["properties"])
    return out


def _failure(model: type, msg: str) -> ValidationError:
    return ValidationError.from_exception_data(model.__name__, [{"type": PydanticCustomError("llm_output", msg), "loc": (), "input": None}])


class GeminiClient(LLMClient):
    def __init__(
        self, api_key: str | None, model: str, cache_dir: Path, cache_enabled: bool = True, cache_refresh: bool = False,
        fallback_from: str = "", *, vertex_project: str | None = None, vertex_location: str = "global",
        thinking_level: str | None = None,
    ) -> None:
        retry = types.HttpRetryOptions(attempts=_MAX_NETWORK_RETRIES + 1)
        # Vertex AI signs in with Google application default credentials; an API key is not sent.
        auth = dict(vertexai=True, project=vertex_project, location=vertex_location) if vertex_project else dict(api_key=api_key)
        self._client = genai.Client(**auth, http_options=types.HttpOptions(retry_options=retry))
        self.model = model
        self.fallback_from = fallback_from
        self.thinking_level = thinking_level  # "low", "medium", ...; None keeps the model's default
        self._schema_level: dict[str, int] = {}  # output model name -> 0 full schema, 1 relaxed, 2 schema in prompt
        self.cache = DiskLLMCache(cache_dir, enabled=cache_enabled, refresh=cache_refresh)

    async def _send(self, contents: list[types.Content], config: types.GenerateContentConfig) -> types.GenerateContentResponse:
        """One request; the seam tests replace."""
        return await self._client.aio.models.generate_content(model=self.model, contents=contents, config=config)

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
            model=self.model, system=system, prompt=prompt, schema_name=output_model.__name__, schema_json=schema,
            temperature=temperature, image_hashes=[hashlib.sha256(b).hexdigest() for b in images] if images else None,
        )
        cached = self.cache.get(cache_key)
        if cached is not None:
            try:
                usage = LLMUsage(**{**cached["usage"], "cached": True, "provider": "google", "fallback_from": self.fallback_from})
                return output_model.model_validate(cached["result"]), usage
            except ValidationError:
                pass  # stale or corrupt entry: call the model

        def make_config(level: int, max_out: int) -> types.GenerateContentConfig:
            in_prompt = f"\n\nAnswer with one JSON object that matches this JSON schema:\n{json.dumps(schema)}" if level == 2 else ""
            return types.GenerateContentConfig(
                system_instruction=(system + in_prompt) or None,
                response_mime_type="application/json",
                response_json_schema=(schema, _relaxed(schema), None)[level],
                # temperature is not sent, as for Claude: Google advises the default for its reasoning models, and the
                # disk cache is what makes a run reproducible. It stays in the cache key and the LLMClient contract.
                max_output_tokens=max_out,
                thinking_config=types.ThinkingConfig(thinking_level=self.thinking_level.upper()) if self.thinking_level else None,
            )

        level = self._schema_level.get(output_model.__name__, 0)
        config = make_config(level, max_tokens)
        parts = [*(types.Part.from_bytes(data=b, mime_type="image/png") for b in images or []), types.Part.from_text(text=prompt)]
        contents = [types.Content(role="user", parts=parts)]
        totals = {"input": 0, "output": 0, "cached": 0}
        last_error: ValidationError | None = None

        for attempt in range(1, max_validation_retries + 2):
            while True:
                try:
                    response = await self._send(contents, config)
                    break
                except errors.ClientError as exc:
                    if exc.code != 400 or "too many states" not in str(exc) or level == 2:
                        raise
                    level += 1
                    self._schema_level[output_model.__name__] = level
                    config = make_config(level, config.max_output_tokens or max_tokens)
            u = response.usage_metadata
            if u is not None:
                totals["input"] += u.prompt_token_count or 0  # includes the cached share
                totals["output"] += (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)  # thinking is billed as output
                totals["cached"] += u.cached_content_token_count or 0
            text = response.text or ""
            candidates = getattr(response, "candidates", None) or []
            finish = candidates[0].finish_reason if candidates else None
            if finish == types.FinishReason.MAX_TOKENS:
                limit = config.max_output_tokens or max_tokens
                last_error = _failure(output_model, f"answer cut off at max_output_tokens={limit} (thinking counts toward it)")
                if limit >= _MAX_OUTPUT_CAP:
                    break
                config = config.model_copy(update={"max_output_tokens": min(limit * 2, _MAX_OUTPUT_CAP)})
                continue
            blocked = getattr(getattr(response, "prompt_feedback", None), "block_reason", None)
            if not text and (blocked or finish not in (None, types.FinishReason.STOP)):
                raise _failure(output_model, f"Gemini returned no answer: {blocked or finish}")
            dropped = 0
            try:
                raw = json.loads(text)
                instance = output_model.model_validate(raw)
            except json.JSONDecodeError:
                last_error = _failure(output_model, "no JSON returned")
                contents += [types.Content(role="model", parts=[types.Part.from_text(text=text)]),
                             types.Content(role="user", parts=[types.Part.from_text(text="Answer with one JSON object matching the schema. Try again.")])]
                continue
            except ValidationError as exc:
                instance, dropped = _drop_invalid_list_items(output_model, raw, exc) if isinstance(raw, dict) else (None, 0)
                if instance is None:
                    last_error = exc
                    contents += [
                        types.Content(role="model", parts=[types.Part.from_text(text=text)]),
                        types.Content(role="user", parts=[types.Part.from_text(text=(
                            f"Your JSON failed schema validation on these fields:\n{_format_validation_errors(exc)}\n\n"
                            "Return the whole JSON object again, fixing every field listed above and leaving every other "
                            "field exactly as it was."
                        ))]),
                    ]
                    continue

            usage = LLMUsage(
                input_tokens=totals["input"], output_tokens=totals["output"], cache_read_tokens=totals["cached"],
                attempts=attempt, model=self.model, prompt_version=prompt_version, provider="google", dropped_items=dropped,
                fallback_from=self.fallback_from,
            )
            self.cache.set(cache_key, {"result": instance.model_dump(mode="json"), "usage": usage.model_dump(exclude={"cached", "fallback_from"})})
            return instance, usage

        assert last_error is not None
        raise last_error

