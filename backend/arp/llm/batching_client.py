"""LangChainAnthropicClient that sends each request through the Message Batches API.

Concurrent `_send` calls queue up; the queue is flushed as one batch after
`flush_after_s` with no new call, or as soon as it holds `max_batch` requests.
Each batch is polled until it ends and its results are matched back to callers
by custom_id, never by position.

Every submitted batch is appended to `batch_log` before it is polled, so a
restarted client attaches to a batch that is already paid for instead of
submitting its requests again.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Coroutine
from datetime import UTC, datetime
from pathlib import Path

from anthropic import NotFoundError
from anthropic.types import Message
from anthropic.types.messages import MessageBatch

from arp.llm.base import LLMUsage, T
from arp.llm.langchain_client import LangChainAnthropicClient
from arp.orchestration.step_tally import cancel_requested, record_batch_wait

CUSTOM_ID_LEN = 64


def custom_id(params: dict) -> str:
    """Deterministic id for a request: identical params share one batch entry."""
    blob = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:CUSTOM_ID_LEN]


class BatchRequestFailed(Exception):
    """A batch entry came back errored, expired or canceled (or not at all)."""

    def __init__(self, result_type: str, error: str = "") -> None:
        super().__init__(f"batch request {result_type}" + (f": {error}" if error else ""))
        self.result_type = result_type
        self.error = error


class BatchingLLMClient(LangChainAnthropicClient):
    def __init__(
        self,
        *args,
        batch_log: Path,
        flush_after_s: float = 2.0,
        max_batch: int = 10_000,
        poll_every_s: float = 30.0,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._batch_log = batch_log
        self._log_index: dict[str, str] | None = None  # custom_id -> batch_id, read on first _send
        self._log_rows: dict[str, dict] = {}  # batch_id -> its log row
        self._watching: set[str] = set()  # batch ids being polled right now
        # batch_id -> results its watch streamed past before anyone waited on them,
        # so a send that attaches mid-stream still gets its result.
        self._streamed: dict[str, dict[str, Message | BaseException]] = {}
        self._flush_after_s = flush_after_s
        self._max_batch = max_batch
        self._poll_every_s = poll_every_s
        # No asyncio.Lock: every mutation of these maps below runs without an
        # await in between, so it is already atomic on the event loop.
        self._pending: dict[str, tuple[dict, list[asyncio.Future]]] = {}
        self._in_flight: dict[str, list[asyncio.Future]] = {}
        self._timer: asyncio.TimerHandle | None = None
        self._tasks: set[asyncio.Task] = set()  # strong refs so running batches aren't GC'd

    async def complete_structured(self, **kwargs) -> tuple[T, LLMUsage]:
        instance, usage = await super().complete_structured(**kwargs)
        return instance, usage if usage.cached else usage.model_copy(update={"batch": True})

    async def _send(self, params: dict) -> Message:
        cid = custom_id(params)
        batch_id = self._logged().pop(cid, None)  # only a custom_id's first send reattaches
        if batch_id is not None:
            try:
                return await self._attach(cid, batch_id)
            except (BatchRequestFailed, NotFoundError):
                if cancel_requested():
                    raise
                # It failed last time, or the batch is gone (results expire): submit afresh.
        # ponytail: an identical call sharing a reattach that fails gets the failure
        # rather than falling through too; rare (needs two identical first sends).
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        if cid in self._in_flight:  # identical request already submitted: share its result
            self._in_flight[cid].append(fut)
            return await fut
        self._pending.setdefault(cid, (params, []))[1].append(fut)
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if len(self._pending) >= self._max_batch:
            self._flush()
        else:
            self._timer = loop.call_later(self._flush_after_s, self._flush)
        return await fut

    def _logged(self) -> dict[str, str]:
        """custom_id -> batch_id from the batch log, read once; a later row wins."""
        if self._log_index is None:
            self._log_index = {}
            if self._batch_log.exists():
                for line in self._batch_log.read_text().splitlines():
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:  # torn last line from a crash mid-append
                        continue
                    self._log_rows[row["batch_id"]] = row
                    self._log_index.update(dict.fromkeys(row["custom_ids"], row["batch_id"]))
        return self._log_index

    def _attach(self, cid: str, batch_id: str) -> asyncio.Future:
        fut = asyncio.get_running_loop().create_future()
        passed = self._streamed.get(batch_id, {})
        if cid in passed:  # its watch already streamed past this id
            result = passed.pop(cid)
            if isinstance(result, BaseException):
                fut.set_exception(result)
            else:
                fut.set_result(result)
            return fut
        self._in_flight.setdefault(cid, []).append(fut)
        if batch_id not in self._watching:
            row = self._log_rows[batch_id]
            # Only ids whose latest row is this batch: an older row's result must not settle them.
            cids = {cid} | {c for c in row["custom_ids"] if self._log_index.get(c) == batch_id}
            self._start(self._watch(batch_id, cids, row["submitted_at"]))
        return fut

    def _flush(self) -> None:
        self._timer = None
        # Drop requests whose every caller was cancelled while queued.
        live = {cid: entry for cid, entry in self._pending.items() if not all(f.done() for f in entry[1])}
        self._pending = {}
        if not live:
            return
        for cid, (_, futs) in live.items():
            self._in_flight[cid] = futs
        # A call_later callback runs in the context captured when it was
        # scheduled, so the batch task inherits the last caller's run.
        self._start(self._run_batch({cid: params for cid, (params, _) in live.items()}))

    def _start(self, coro: Coroutine) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _settle(self, cid: str, result: Message | BaseException) -> None:
        for fut in self._in_flight.pop(cid, ()):
            if fut.done():  # caller was cancelled
                continue
            if isinstance(result, BaseException):
                fut.set_exception(result)
            else:
                fut.set_result(result)

    async def _run_batch(self, chunk: dict[str, dict]) -> None:
        try:
            batch = await self._client.messages.batches.create(
                requests=[{"custom_id": cid, "params": p} for cid, p in chunk.items()]
            )
            row = {"batch_id": batch.id, "custom_ids": list(chunk), "submitted_at": datetime.now(UTC).isoformat()}
            # On disk before the first poll: a crash from here on still leaves the batch reusable.
            self._batch_log.parent.mkdir(parents=True, exist_ok=True)  # cache_dir is only made when the disk cache is on
            with self._batch_log.open("a") as f:
                f.write(json.dumps(row) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception as exc:
            for cid in chunk:
                self._settle(cid, exc)
            return
        self._log_rows[batch.id] = row
        await self._watch(batch.id, set(chunk), row["submitted_at"], batch)

    async def _watch(self, batch_id: str, cids: set[str], submitted_at: str, batch: MessageBatch | None = None) -> None:
        """Poll a batch until it ends, then settle the waiters on `cids` from its results."""
        batches = self._client.messages.batches
        self._watching.add(batch_id)
        seen: set[str] = set()
        # ponytail: holds unwaited results until the stream ends (a full batch's worth on resume).
        passed = self._streamed[batch_id] = {}
        try:
            if batch is None:
                batch = await batches.retrieve(batch_id)
            if batch.processing_status != "ended":
                record_batch_wait(
                    {"batch_id": batch_id, "request_count": len(cids), "submitted_at": submitted_at, "status": "in_progress"}
                )
            while batch.processing_status != "ended":
                await asyncio.sleep(self._poll_every_s)
                if cancel_requested():
                    await batches.cancel(batch_id)
                    for cid in cids:
                        self._settle(cid, BatchRequestFailed("canceled", "the run was cancelled"))
                    return
                batch = await batches.retrieve(batch_id)
            async for entry in await batches.results(batch_id):
                if entry.custom_id not in cids:
                    continue
                seen.add(entry.custom_id)
                r = entry.result
                if r.type == "succeeded":
                    result = r.message
                else:
                    result = BatchRequestFailed(r.type, r.error.error.message if r.type == "errored" else "")
                if entry.custom_id in self._in_flight:
                    self._settle(entry.custom_id, result)
                else:
                    passed[entry.custom_id] = result
        except Exception as exc:
            # The batch may well still be running server-side: let the next
            # send of these requests reattach to it rather than pay again.
            self._logged().update(dict.fromkeys(cids - seen, batch_id))
            for cid in cids - seen:
                self._settle(cid, exc)
        finally:
            self._streamed.pop(batch_id, None)
            self._watching.discard(batch_id)
            if not self._watching:
                record_batch_wait(None)
            for cid in cids - seen:
                if cid in self._in_flight:
                    self._settle(cid, BatchRequestFailed("missing", "no result returned for this request"))
