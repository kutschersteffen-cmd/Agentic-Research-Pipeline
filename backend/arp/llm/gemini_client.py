"""LLMClient backed by Google's `google-genai` SDK, for `gemini-*` models.

Same contract as LangChainAnthropicClient: a schema-validated `output_model` instance, a bounded
validation-retry loop that shows the model its errors, SDK-level retries for transient errors, PNG
images ahead of the prompt, and the shared disk cache (keys include the model id, so Claude and Gemini
entries never collide). Structured output uses Gemini's JSON mode with the model's full JSON schema.

Caching: Gemini caches a shared request prefix of at least 4,096 tokens on its own (implicit caching);
the cached share comes back as `cached_content_token_count` and is reported as cache_read_tokens.
Explicit cache objects are not used (Gemini 4 Argon does not support them). Batch: no Gemini batch
client yet, so a batch run sends Gemini calls one by one (see llm/factory.py)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from google import genai
from google.genai import types
from pydantic import ValidationError

from arp.llm.base import LLMClient, LLMUsage, T
from arp.llm.cache import DiskLLMCache
from arp.llm.langchain_client import _MAX_NETWORK_RETRIES, _drop_invalid_list_items, _format_validation_errors, logger


class GeminiClient(LLMClient):
    def __init__(
        self, api_key: str, model: str, cache_dir: Path, cache_enabled: bool = True, cache_refresh: bool = False,
    ) -> None:
        retry = types.HttpRetryOptions(attempts=_MAX_NETWORK_RETRIES + 1)
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(retry_options=retry))
        self.model = model
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
                usage = LLMUsage(**{**cached["usage"], "cached": True, "provider": "google"})
                return output_model.model_validate(cached["result"]), usage
            except ValidationError:
                pass  # stale or corrupt entry: call the model

        config = types.GenerateContentConfig(
            system_instruction=system or None,
            response_mime_type="application/json",
            response_json_schema=schema,
            # temperature is not sent, as for Claude: Google advises the default for its reasoning models, and the
            # disk cache is what makes a run reproducible. It stays in the cache key and the LLMClient contract.
            max_output_tokens=max_tokens,
        )
        parts = [*(types.Part.from_bytes(data=b, mime_type="image/png") for b in images or []), types.Part.from_text(text=prompt)]
        contents = [types.Content(role="user", parts=parts)]
        totals = {"input": 0, "output": 0, "cached": 0}
        last_error: ValidationError | None = None

        for attempt in range(1, max_validation_retries + 2):
            response = await self._send(contents, config)
            u = response.usage_metadata
            if u is not None:
                totals["input"] += u.prompt_token_count or 0  # includes the cached share
                totals["output"] += (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)  # thinking is billed as output
                totals["cached"] += u.cached_content_token_count or 0
            text = response.text or ""
            try:
                raw = json.loads(text)
                instance = output_model.model_validate(raw)
            except json.JSONDecodeError:
                last_error = ValidationError.from_exception_data(
                    output_model.__name__, [{"type": "missing", "loc": (), "input": None, "msg": "no JSON returned"}]
                )
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
                if dropped:
                    logger.info("%s: dropped %d invalid list item(s) rather than requesting a full retry (%s)",
                                output_model.__name__, dropped, exc)

            usage = LLMUsage(
                input_tokens=totals["input"], output_tokens=totals["output"], cache_read_tokens=totals["cached"],
                attempts=attempt, model=self.model, prompt_version=prompt_version, provider="google",
            )
            self.cache.set(cache_key, {"result": instance.model_dump(mode="json"), "usage": usage.model_dump(exclude={"cached"})})
            return instance, usage

        assert last_error is not None
        raise last_error

