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
    ) * input_price * 1.25
    assert abs(cost - expected) < 1e-9


def test_estimate_cost_usd_reads_cache_at_005_on_sonnet_and_opus_5_5():
    usage = LLMUsage(input_tokens=1_000_000, output_tokens=0, cache_read_tokens=1_000_000)
    assert abs(estimate_cost_usd("claude-sonnet-5-5", usage) - 0.10) < 1e-9
    assert abs(estimate_cost_usd("claude-opus-5-5", usage) - 0.20) < 1e-9


def test_combine_usage_leaves_out_disk_cache_hits():
    live = LLMUsage(input_tokens=100, output_tokens=10)
    hit = LLMUsage(input_tokens=900, output_tokens=90, cached=True)
    combined = combine_usage(live, hit)
    assert (combined.input_tokens, combined.output_tokens, combined.cached) == (100, 10, False)
    assert combine_usage(hit, hit).cached


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


def test_estimate_cost_usd_halves_for_batch():
    usage = LLMUsage(input_tokens=1_000_000, output_tokens=1_000_000, batch=True)
    assert estimate_cost_usd("claude-sonnet-5-5", usage) == 6.0


def test_combine_usage_keeps_batch_flag():
    assert combine_usage(LLMUsage(batch=True), LLMUsage(batch=True)).batch is True
