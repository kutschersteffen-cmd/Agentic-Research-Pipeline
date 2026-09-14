from arp.llm.base import LLMUsage
from arp.orchestration.cost_tracker import combine_usage, estimate_cost_usd


def test_estimate_cost_usd_plain_input_output():
    usage = LLMUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert estimate_cost_usd("claude-sonnet-5", usage) == 2.0 + 10.0


def test_estimate_cost_usd_applies_cache_read_and_write_multipliers():
    # 500k base input, 300k served from cache read, 200k written to cache
    # (input_tokens is already the grand total including both).
    usage = LLMUsage(
        input_tokens=1_000_000, output_tokens=0, cache_read_tokens=300_000, cache_creation_tokens=200_000
    )
    cost = estimate_cost_usd("claude-sonnet-5", usage)
    input_price = 2.0
    expected = (500_000 / 1_000_000) * input_price + (300_000 / 1_000_000) * input_price * 0.1 + (
        200_000 / 1_000_000
    ) * input_price * 2.0
    assert abs(cost - expected) < 1e-9


def test_estimate_cost_usd_zero_for_disk_cached_result():
    usage = LLMUsage(input_tokens=1_000_000, output_tokens=1_000_000, cached=True)
    assert estimate_cost_usd("claude-sonnet-5", usage) == 0.0


def test_estimate_cost_usd_unknown_model_falls_back_to_default_price():
    usage = LLMUsage(input_tokens=1_000_000, output_tokens=0)
    assert estimate_cost_usd("some-future-model", usage) == 3.0


def test_combine_usage_sums_cache_token_fields():
    a = LLMUsage(input_tokens=100, output_tokens=10, cache_read_tokens=50, cache_creation_tokens=20)
    b = LLMUsage(input_tokens=200, output_tokens=20, cache_read_tokens=150, cache_creation_tokens=0)
    combined = combine_usage(a, b)
    assert combined.input_tokens == 300
    assert combined.output_tokens == 30
    assert combined.cache_read_tokens == 200
    assert combined.cache_creation_tokens == 20
