from __future__ import annotations

import logging

from arp.config import Settings
from arp.errors import NotConfigured
from arp.llm.base import LLMClient
from arp.llm.batching_client import BatchingLLMClient
from arp.llm.fallback_client import FallbackLLMClient
from arp.llm.gemini_client import GeminiClient
from arp.llm.langchain_client import LangChainAnthropicClient

log = logging.getLogger("arp.llm.fallback_client")


def batch_settings(settings: Settings, batch: bool) -> Settings:
    """`settings` for a batch run when `batch`, else `settings` itself."""
    if not batch:
        return settings
    return settings.model_copy(update={"llm_batch": True, "max_concurrent_llm_calls": settings.batch_concurrency})


def build_llm_client(
    settings: Settings, *, model: str | None = None, cache_refresh: bool | None = None, verifier: bool = False,
) -> LLMClient:
    if settings.standins_dir is not None:
        from arp.standins import StandInLLMClient

        return StandInLLMClient(settings.standins_dir)
    model = model or settings.llm_model
    refresh = settings.llm_cache_refresh if cache_refresh is None else cache_refresh
    if model.startswith("gemini-"):
        if not settings.gemini_api_key:
            raise NotConfigured(f"ARP_GEMINI_API_KEY is not set, and the run uses the Gemini model {model}.")
        # shortcut: no Gemini batch client, so a batch run sends Gemini calls one by one; add one if volume needs it
        return GeminiClient(
            api_key=settings.gemini_api_key, model=model, cache_dir=settings.cache_dir,
            cache_enabled=settings.llm_cache_enabled, cache_refresh=refresh,
        )
    gemini_model = settings.gemini_fallback_verifier_model if verifier else settings.gemini_fallback_model
    independence = ""
    if verifier and settings.gemini_fallback_model == settings.gemini_fallback_verifier_model:
        independence = " The verifier now runs on the same Gemini model as the extractor: verifier independence is relaxed."
    warning = f"Claude model {model} is replaced by Gemini model {gemini_model}.{independence}"

    def gemini() -> GeminiClient:
        return GeminiClient(
            api_key=settings.gemini_api_key, model=gemini_model, cache_dir=settings.cache_dir,
            cache_enabled=settings.llm_cache_enabled, cache_refresh=refresh, fallback_from=model,
        )

    if not settings.anthropic_api_key and settings.gemini_api_key:
        log.warning(warning)
        return gemini()
    if not settings.anthropic_api_key:
        raise NotConfigured(
            "ARP_ANTHROPIC_API_KEY is not set. Provide an Anthropic API key via environment variable "
            "or a .env file before running any agent pipeline."
        )
    kwargs = dict(
        api_key=settings.anthropic_api_key,
        model=model,
        cache_dir=settings.cache_dir,
        cache_enabled=settings.llm_cache_enabled,
        cache_refresh=refresh,
        prompt_cache_enabled=settings.llm_prompt_cache_enabled,
    )
    if settings.llm_batch:
        # A new client per call: batch waits and cancels follow the run that awaits them.
        primary: LLMClient = BatchingLLMClient(**kwargs, batch_log=settings.cache_dir / "llm_batches.jsonl")
    else:
        primary = LangChainAnthropicClient(**kwargs)
    return FallbackLLMClient(primary, gemini, warning) if settings.gemini_api_key else primary


def build_verifier_llm_client(settings: Settings) -> LLMClient:
    """A second client, deliberately on `llm_verifier_model` rather than
    `llm_model`, for every independent Verifier/Kritiker call (extraction,
    financials). Decorrelates errors: an extractor and a verifier running
    on identical weights can both miss the same class of mistake, which
    defeats the point of an "independent" verification pass. Shares the
    same disk cache directory as the extractor client -- cache keys already
    include the model id, so entries for the two models never collide."""
    return build_llm_client(
        settings, model=settings.llm_verifier_model, verifier=True,
        cache_refresh=settings.llm_cache_refresh or settings.llm_verifier_cache_refresh,
    )
