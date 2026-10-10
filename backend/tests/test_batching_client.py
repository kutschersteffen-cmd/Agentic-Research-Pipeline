import asyncio

import httpx
from anthropic import APIConnectionError
from pydantic import BaseModel

from arp.llm.batching_client import CUSTOM_ID_LEN, BatchingLLMClient, BatchRequestFailed, custom_id
from tests.fake_batches import FakeBatches


class _Out(BaseModel):
    echo: str


def _client(tmp_path, cache_enabled: bool = False, **kwargs) -> tuple[BatchingLLMClient, FakeBatches]:
    client = BatchingLLMClient(
        api_key="test",
        model="test-model",
        cache_dir=tmp_path,
        cache_enabled=cache_enabled,
        batch_log=tmp_path / "llm_batches.jsonl",
        flush_after_s=0.01,
        poll_every_s=0.01,
        **kwargs,
    )
    fake = FakeBatches()
    client._client.messages.batches = fake
    return client, fake


def _call(client, prompt: str):
    return client.complete_structured(system="sys", prompt=prompt, output_model=_Out)


def test_custom_id_is_stable_64_hex():
    a = custom_id({"b": 1, "a": [1, 2]})
    assert a == custom_id({"a": [1, 2], "b": 1})
    assert len(a) == CUSTOM_ID_LEN == 64
    int(a, 16)


async def test_concurrent_calls_flush_as_one_batch(tmp_path):
    client, fake = _client(tmp_path)
    prompts = [f"p{i}" for i in range(5)]
    results = await asyncio.gather(*(_call(client, p) for p in prompts))
    assert [len(r) for r in fake.creates] == [5]
    assert [out.echo for out, _ in results] == prompts


async def test_results_out_of_order_reach_right_caller(tmp_path):
    client, fake = _client(tmp_path)
    fake.reverse = True
    prompts = [f"p{i}" for i in range(4)]
    results = await asyncio.gather(*(_call(client, p) for p in prompts))
    assert [out.echo for out, _ in results] == prompts


async def test_max_batch_splits(tmp_path):
    client, fake = _client(tmp_path, max_batch=3)
    prompts = [f"p{i}" for i in range(7)]
    results = await asyncio.gather(*(_call(client, p) for p in prompts))
    assert [len(r) for r in fake.creates] == [3, 3, 1]
    assert [out.echo for out, _ in results] == prompts


async def test_late_call_goes_in_next_batch(tmp_path):
    client, fake = _client(tmp_path)
    fake.hold = True
    first = [asyncio.create_task(_call(client, p)) for p in ("a", "b")]
    while not fake.creates:
        await asyncio.sleep(0.005)
    third = asyncio.create_task(_call(client, "c"))
    while len(fake.creates) < 2:
        await asyncio.sleep(0.005)
    assert not any(t.done() for t in [*first, third])
    fake.release()
    results = await asyncio.gather(*first, third)
    assert [len(r) for r in fake.creates] == [2, 1]
    assert [out.echo for out, _ in results] == ["a", "b", "c"]


async def test_identical_requests_share_one_batch_entry(tmp_path):
    client, fake = _client(tmp_path)
    results = await asyncio.gather(_call(client, "same"), _call(client, "same"))
    assert [len(r) for r in fake.creates] == [1]
    assert [out.echo for out, _ in results] == ["same", "same"]


async def _one_bad_of_three(tmp_path, kind):
    client, fake = _client(tmp_path)
    fake.outcomes["bad"] = kind
    results = await asyncio.gather(_call(client, "ok1"), _call(client, "bad"), _call(client, "ok2"), return_exceptions=True)
    assert [len(r) for r in fake.creates] == [3]
    assert results[0][0].echo == "ok1" and results[2][0].echo == "ok2"
    assert isinstance(results[1], BatchRequestFailed)
    assert results[1].result_type == kind
    if kind == "errored":
        assert "fake failure" in results[1].error


async def test_errored_request_fails_only_its_caller(tmp_path):
    await _one_bad_of_three(tmp_path, "errored")


async def test_expired_request_fails_its_caller(tmp_path):
    await _one_bad_of_three(tmp_path, "expired")


async def test_submit_failure_fails_all_callers(tmp_path):
    client, fake = _client(tmp_path)
    fake.create_error = APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages/batches"))
    results = await asyncio.gather(_call(client, "a"), _call(client, "b"), return_exceptions=True)
    assert all(isinstance(r, APIConnectionError) for r in results)
    out, _ = await _call(client, "c")
    assert out.echo == "c"


async def test_disk_cache_hit_never_enqueues(tmp_path):
    warm, _ = _client(tmp_path, cache_enabled=True)
    await _call(warm, "cached prompt")
    client, fake = _client(tmp_path, cache_enabled=True)
    _, usage = await _call(client, "cached prompt")
    assert usage.cached is True
    assert usage.batch is False
    assert fake.creates == []


async def test_usage_marked_batch(tmp_path):
    client, _ = _client(tmp_path)
    _, usage = await _call(client, "live")
    assert usage.batch is True
    assert usage.cached is False
