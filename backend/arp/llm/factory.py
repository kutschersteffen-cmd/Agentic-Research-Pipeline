from __future__ import annotations

from arp.config import Settings
from arp.llm.anthropic_client import AnthropicLLMClient
from arp.llm.base import LLMClient


def build_llm_client(settings: Settings) -> LLMClient:
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ARP_ANTHROPIC_API_KEY is not set. Provide an Anthropic API key via environment variable "
            "or a .env file before running any agent pipeline."
        )
    return AnthropicLLMClient(
        api_key=settings.anthropic_api_key,
        model=settings.llm_model,
        cache_dir=settings.cache_dir,
        cache_enabled=settings.llm_cache_enabled,
    )
