from __future__ import annotations

from collections.abc import Callable

from arp.config import Settings
from arp.llm.base import LLMClient
from arp.llm.langchain_client import LangChainAnthropicClient


def _build_anthropic(settings: Settings, *, model: str | None = None, cache_refresh: bool | None = None) -> LLMClient:
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ARP_ANTHROPIC_API_KEY is not set. Provide an Anthropic API key via environment variable "
            "or a .env file before running any agent pipeline."
        )
    return LangChainAnthropicClient(
        api_key=settings.anthropic_api_key,
        model=model or settings.llm_model,
        cache_dir=settings.cache_dir,
        cache_enabled=settings.llm_cache_enabled,
        cache_refresh=settings.llm_cache_refresh if cache_refresh is None else cache_refresh,
        prompt_cache_enabled=settings.llm_prompt_cache_enabled,
    )


_BUILDERS: dict[str, Callable[..., LLMClient]] = {"anthropic": _build_anthropic}


def build_llm_client(settings: Settings, *, model: str | None = None, cache_refresh: bool | None = None) -> LLMClient:
    return _BUILDERS[settings.llm_provider](settings, model=model, cache_refresh=cache_refresh)


def build_verifier_llm_client(settings: Settings) -> LLMClient:
    """A second client, deliberately on `llm_verifier_model` rather than
    `llm_model`, for every independent Verifier/Kritiker call (extraction,
    financials). Decorrelates errors: an extractor and a verifier running
    on identical weights can both miss the same class of mistake, which
    defeats the point of an "independent" verification pass. Shares the
    same disk cache directory as the extractor client -- cache keys already
    include the model id, so entries for the two models never collide."""
    return build_llm_client(settings, model=settings.llm_verifier_model, cache_refresh=settings.llm_cache_refresh or settings.llm_verifier_cache_refresh)
