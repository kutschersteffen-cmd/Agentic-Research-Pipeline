
from arp.orchestration.batch_runner import run_batch, run_sinks
from arp.storage.run_store import RunStore


async def test_run_batch_writes_results_and_is_resumable(tmp_path):
    store = RunStore(tmp_path)
    items = ["a", "b", "c"]
    calls = []

    async def worker(item: str) -> str:
        calls.append(item)
        return item.upper()

    await run_batch(
        items,
        item_key=lambda i: i,
        worker=worker,
        sinks=run_sinks(store, 'r'),
        concurrency=2,
        result_to_json=lambda r: {"value": r},
    )
    assert set(calls) == {"a", "b", "c"}
    rows = store.read_results("r")
    assert {r["value"] for r in rows} == {"A", "B", "C"}

    # second run over the same items + a new one should skip the done ones
    calls.clear()
    await run_batch(
        ["a", "b", "c", "d"],
        item_key=lambda i: i,
        worker=worker,
        sinks=run_sinks(store, 'r'),
        concurrency=2,
        result_to_json=lambda r: {"value": r},
    )
    assert calls == ["d"]


async def test_run_batch_isolates_failures(tmp_path):
    store = RunStore(tmp_path)

    async def worker(item: str) -> str:
        if item == "bad":
            raise ValueError("boom")
        return item

    await run_batch(
        ["good1", "bad", "good2"],
        item_key=lambda i: i,
        worker=worker,
        sinks=run_sinks(store, 'r'),
        concurrency=3,
        result_to_json=lambda r: {"value": r},
    )
    result_values = {r["value"] for r in store.read_results("r")}
    assert result_values == {"good1", "good2"}
    error_rows = store.read_errors("r")
    assert len(error_rows) == 1
    assert error_rows[0]["key"] == "bad"


async def test_run_batch_cancel_check_stops_new_items(tmp_path):
    store = RunStore(tmp_path)
    calls = []

    async def worker(item: str) -> str:
        calls.append(item)
        return item

    await run_batch(
        ["a", "b", "c", "d", "e"],
        item_key=lambda i: i,
        worker=worker,
        sinks=run_sinks(store, 'r'),
        concurrency=1,
        result_to_json=lambda r: {"value": r},
        cancel_check=lambda: len(calls) >= 2,
    )
    # Cancellation must have actually stopped something -- not every item ran,
    # and whatever did run is a clean, uncorrupted checkpoint.
    assert len(calls) < 5
    rows = store.read_results("r")
    assert {r["value"] for r in rows} == set(calls)


async def test_run_batch_no_resume_reruns_everything(tmp_path):
    store = RunStore(tmp_path)
    calls = []

    async def worker(item: str) -> str:
        calls.append(item)
        return item

    for _ in range(2):
        await run_batch(
            ["x"],
            item_key=lambda i: i,
            worker=worker,
            sinks=run_sinks(store, 'r'),
            concurrency=1,
            result_to_json=lambda r: {"value": r},
            resume=False,
        )
    assert calls == ["x", "x"]
