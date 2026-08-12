from __future__ import annotations

from arp.llm.base import LLMUsage

# Approximate list prices (USD per 1M tokens). Update as pricing changes;
# this only drives the informational cost estimate shown in run manifests,
# never billing.
_PRICE_PER_MILLION_TOKENS: dict[str, tuple[float, float]] = {
    "claude-opus-5": (15.0, 75.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-fable-5": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (0.8, 4.0),
}
_DEFAULT_PRICE = (3.0, 15.0)


def estimate_cost_usd(model: str, usage: LLMUsage) -> float:
    if usage.cached:
        return 0.0
    input_price, output_price = _PRICE_PER_MILLION_TOKENS.get(model, _DEFAULT_PRICE)
    return (usage.input_tokens / 1_000_000) * input_price + (usage.output_tokens / 1_000_000) * output_price


def combine_usage(*usages: LLMUsage) -> LLMUsage:
    return LLMUsage(
        input_tokens=sum(u.input_tokens for u in usages),
        output_tokens=sum(u.output_tokens for u in usages),
        cached=all(u.cached for u in usages) if usages else False,
    )
