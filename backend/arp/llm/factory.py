from __future__ import annotations

from arp.config import Settings
from arp.llm.base import LLMClient
from arp.llm.langchain_client import LangChainAnthropicClient


def build_llm_client(settings: Settings, *, model: str | None = None) -> LLMClient:
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
    )


def build_verifier_llm_client(settings: Settings) -> LLMClient:
    """A second client, deliberately on `llm_verifier_model` rather than
    `llm_model`, for every independent Verifier/Kritiker call (extraction,
    financials). Decorrelates errors: an extractor and a verifier running
    on identical weights can both miss the same class of mistake, which
    defeats the point of an "independent" verification pass. Shares the
    same disk cache directory as the extractor client -- cache keys already
    include the model id, so entries for the two models never collide."""
    return build_llm_client(settings, model=settings.llm_verifier_model)
