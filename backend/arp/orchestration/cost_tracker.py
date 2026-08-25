from __future__ import annotations

from arp.llm.base import LLMUsage

# List prices (USD per 1M tokens). Update as pricing changes; this only
# drives the informational cost estimate shown in run manifests, never
# billing. Corrected against Anthropic's current published rates -- several
# entries here had drifted (e.g. claude-sonnet-5 was listed at $3/$15,
# actually $2/$10).
_PRICE_PER_MILLION_TOKENS: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}
_DEFAULT_PRICE = (3.0, 15.0)

# Anthropic prices a prompt-cache read far below, and a cache write somewhat
# above, the normal input rate -- see arp/llm/langchain_client.py, which
# always writes with a 1h TTL.
_CACHE_READ_MULTIPLIER = 0.1
_CACHE_WRITE_MULTIPLIER = 2.0  # 1h TTL; would be 1.25 for the 5m default


def estimate_cost_usd(model: str, usage: LLMUsage) -> float:
    if usage.cached:
        return 0.0
    input_price, output_price = _PRICE_PER_MILLION_TOKENS.get(model, _DEFAULT_PRICE)
    # input_tokens is already the grand total (base + cache_read + cache_creation --
    # see LangChainAnthropicClient), so the base/regular share is the remainder.
    base_input_tokens = usage.input_tokens - usage.cache_read_tokens - usage.cache_creation_tokens
    return (
        (base_input_tokens / 1_000_000) * input_price
        + (usage.cache_read_tokens / 1_000_000) * input_price * _CACHE_READ_MULTIPLIER
        + (usage.cache_creation_tokens / 1_000_000) * input_price * _CACHE_WRITE_MULTIPLIER
        + (usage.output_tokens / 1_000_000) * output_price
    )


def combine_usage(*usages: LLMUsage) -> LLMUsage:
    return LLMUsage(
        input_tokens=sum(u.input_tokens for u in usages),
        output_tokens=sum(u.output_tokens for u in usages),
        cache_read_tokens=sum(u.cache_read_tokens for u in usages),
        cache_creation_tokens=sum(u.cache_creation_tokens for u in usages),
        cached=all(u.cached for u in usages) if usages else False,
    )
