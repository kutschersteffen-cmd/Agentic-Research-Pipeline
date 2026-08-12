import json

import pytest

from arp.orchestration.batch_runner import run_batch


async def test_run_batch_writes_results_and_is_resumable(tmp_path):
    results_path = tmp_path / "results.jsonl"
    errors_path = tmp_path / "errors.jsonl"
    items = ["a", "b", "c"]
    calls = []

    async def worker(item: str) -> str:
        calls.append(item)
        return item.upper()

    await run_batch(
        items,
        item_key=lambda i: i,
        worker=worker,
        results_path=results_path,
        errors_path=errors_path,
        concurrency=2,
        result_to_json=lambda r: {"value": r},
    )
    assert set(calls) == {"a", "b", "c"}
    rows = [json.loads(line) for line in results_path.read_text().splitlines()]
    assert {r["value"] for r in rows} == {"A", "B", "C"}

    # second run over the same items + a new one should skip the done ones
    calls.clear()
    await run_batch(
        ["a", "b", "c", "d"],
        item_key=lambda i: i,
        worker=worker,
        results_path=results_path,
        errors_path=errors_path,
        concurrency=2,
        result_to_json=lambda r: {"value": r},
    )
    assert calls == ["d"]


async def test_run_batch_isolates_failures(tmp_path):
    results_path = tmp_path / "results.jsonl"
    errors_path = tmp_path / "errors.jsonl"

    async def worker(item: str) -> str:
        if item == "bad":
            raise ValueError("boom")
        return item

    await run_batch(
        ["good1", "bad", "good2"],
        item_key=lambda i: i,
        worker=worker,
        results_path=results_path,
        errors_path=errors_path,
        concurrency=3,
        result_to_json=lambda r: {"value": r},
    )
    result_values = {json.loads(line)["value"] for line in results_path.read_text().splitlines()}
    assert result_values == {"good1", "good2"}
    error_rows = [json.loads(line) for line in errors_path.read_text().splitlines()]
    assert len(error_rows) == 1
    assert error_rows[0]["key"] == "bad"


async def test_run_batch_no_resume_reruns_everything(tmp_path):
    results_path = tmp_path / "results.jsonl"
    errors_path = tmp_path / "errors.jsonl"
    calls = []

    async def worker(item: str) -> str:
        calls.append(item)
        return item

    for _ in range(2):
        await run_batch(
            ["x"],
            item_key=lambda i: i,
            worker=worker,
            results_path=results_path,
            errors_path=errors_path,
            concurrency=1,
            result_to_json=lambda r: {"value": r},
            resume=False,
        )
    assert calls == ["x", "x"]
