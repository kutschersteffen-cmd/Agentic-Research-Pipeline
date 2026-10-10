import asyncio
import json

import httpx
from anthropic import APIConnectionError
from pydantic import BaseModel

from arp.llm.batching_client import CUSTOM_ID_LEN, BatchingLLMClient, BatchRequestFailed, custom_id
from arp.orchestration.job_manager import JobManager
from arp.orchestration.step_tally import tally_run
from arp.storage.run_store import RunStore
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
    assert fake.retrieves >= 1  # create returns in_progress, so the poll loop ran
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


async def _wait_for(cond):
    while not cond():
        await asyncio.sleep(0.005)


def _log_rows(tmp_path) -> list[dict]:
    return [json.loads(line) for line in (tmp_path / "llm_batches.jsonl").read_text().splitlines()]


async def test_restart_reuses_ended_batch(tmp_path):
    a, fake = _client(tmp_path)
    await _call(a, "x")
    [row] = _log_rows(tmp_path)
    assert row["batch_id"] == "msgbatch_1" and len(row["custom_ids"]) == 1 and row["submitted_at"]
    b, _ = _client(tmp_path)
    b._client.messages.batches = fake
    out, _ = await _call(b, "x")
    assert out.echo == "x"
    assert len(fake.creates) == 1


async def test_restart_waits_on_in_progress_batch(tmp_path):
    a, fake = _client(tmp_path)
    fake.hold = True
    crashed = asyncio.create_task(_call(a, "x"))
    await _wait_for(lambda: fake.creates)
    crashed.cancel()  # client A's process is gone; its batch keeps running
    b, _ = _client(tmp_path)
    b._client.messages.batches = fake
    waiting = asyncio.create_task(_call(b, "x"))
    await asyncio.sleep(0.05)
    assert not waiting.done()
    fake.release()
    out, _ = await waiting
    assert out.echo == "x"
    assert len(fake.creates) == 1


async def test_restart_reattaches_after_poll_failure(tmp_path):
    a, fake = _client(tmp_path)
    fake.retrieve_error = APIConnectionError(request=httpx.Request("GET", "https://api.anthropic.com/v1/messages/batches/x"))
    results = await asyncio.gather(_call(a, "x"), return_exceptions=True)
    assert isinstance(results[0], APIConnectionError)
    assert len(_log_rows(tmp_path)) == 1
    b, _ = _client(tmp_path)
    b._client.messages.batches = fake
    out, _ = await _call(b, "x")
    assert out.echo == "x"
    assert len(fake.creates) == 1


async def test_same_client_retry_reattaches_after_poll_failure(tmp_path):
    client, fake = _client(tmp_path)
    fake.retrieve_error = APIConnectionError(request=httpx.Request("GET", "https://api.anthropic.com/v1/messages/batches/x"))
    results = await asyncio.gather(_call(client, "x"), return_exceptions=True)
    assert isinstance(results[0], APIConnectionError)
    out, _ = await _call(client, "x")
    assert out.echo == "x"
    assert len(fake.creates) == 1


async def test_restart_resubmits_when_logged_entry_failed(tmp_path):
    a, fake = _client(tmp_path)
    fake.outcomes["x"] = "expired"
    results = await asyncio.gather(_call(a, "x"), return_exceptions=True)
    assert isinstance(results[0], BatchRequestFailed)
    b, _ = _client(tmp_path)
    b._client.messages.batches = fake
    results = await asyncio.gather(_call(b, "x"), return_exceptions=True)
    # B read the logged (expired) entry, then submitted the request afresh.
    assert len(fake.creates) == 2
    assert isinstance(results[0], BatchRequestFailed) and results[0].result_type == "expired"


async def test_late_attach_while_results_stream_past_it(tmp_path):
    a, fake = _client(tmp_path)
    await asyncio.gather(_call(a, "x"), _call(a, "y"))
    fake.reverse = True  # y streams first, before anyone on B waits for it
    fake.stream_delay = 0.05
    b, _ = _client(tmp_path)
    b._client.messages.batches = fake
    first = asyncio.create_task(_call(b, "x"))
    await asyncio.sleep(0.03)
    out, _ = await asyncio.wait_for(_call(b, "y"), 1)
    assert out.echo == "y"
    assert (await first)[0].echo == "x"
    assert len(fake.creates) == 1


def _run(tmp_path) -> tuple[RunStore, JobManager, str]:
    store = RunStore(tmp_path / "runs")
    jm = JobManager(store)
    return store, jm, jm.create_run("theme", {}, company_count=1).run_id


async def test_cancel_requested_cancels_batch(tmp_path):
    store, jm, run_id = _run(tmp_path)
    client, fake = _client(tmp_path)
    fake.hold = True
    with tally_run(store, run_id):
        calls = [asyncio.create_task(_call(client, p)) for p in ("a", "b")]
        await _wait_for(lambda: fake.creates)
        jm.request_cancel(run_id)
        results = await asyncio.gather(*calls, return_exceptions=True)
    assert fake.cancels == ["msgbatch_1"]
    assert all(isinstance(r, BatchRequestFailed) and r.result_type == "canceled" for r in results)


async def test_batch_wait_written_and_cleared(tmp_path):
    store, jm, run_id = _run(tmp_path)
    client, fake = _client(tmp_path)
    fake.hold = True
    with tally_run(store, run_id):
        # Flushed by the call_later timer: the batch must still see this run's context.
        calls = [asyncio.create_task(_call(client, p)) for p in ("a", "b", "c")]
        await _wait_for(lambda: fake.retrieves)
        wait = store.load_manifest(run_id).batch_wait
        assert wait["request_count"] == 3
        assert wait["batch_id"] == "msgbatch_1" and wait["status"] == "in_progress" and wait["submitted_at"]
        fake.release()
        await asyncio.gather(*calls)
    assert store.load_manifest(run_id).batch_wait is None


async def test_caller_cancelled_before_flush_is_not_submitted(tmp_path):
    client, fake = _client(tmp_path)
    gone = asyncio.create_task(_call(client, "gone"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    gone.cancel()
    out, _ = await _call(client, "kept")
    assert out.echo == "kept"
    assert [len(r) for r in fake.creates] == [1]


async def test_all_callers_cancelled_submits_nothing(tmp_path):
    client, fake = _client(tmp_path)
    gone = asyncio.create_task(_call(client, "gone"))
    await _wait_for(lambda: client._pending)
    gone.cancel()
    await asyncio.sleep(0.05)
    assert fake.creates == []
