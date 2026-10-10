"""LangChainAnthropicClient that sends each request through the Message Batches API.

Concurrent `_send` calls queue up; the queue is flushed as one batch after
`flush_after_s` with no new call, or as soon as it holds `max_batch` requests.
Each batch is polled until it ends and its results are matched back to callers
by custom_id, never by position.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from anthropic.types import Message

from arp.llm.base import LLMUsage, T
from arp.llm.langchain_client import LangChainAnthropicClient

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
        self._batch_log = batch_log  # written by the restart-reuse logic, not yet
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
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        cid = custom_id(params)
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

    def _flush(self) -> None:
        self._timer = None
        chunk = {cid: params for cid, (params, _) in self._pending.items()}
        for cid, (_, futs) in self._pending.items():
            self._in_flight[cid] = futs
        self._pending = {}
        task = asyncio.get_running_loop().create_task(self._run_batch(chunk))
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
        batches = self._client.messages.batches
        try:
            batch = await batches.create(requests=[{"custom_id": cid, "params": p} for cid, p in chunk.items()])
            while batch.processing_status != "ended":
                await asyncio.sleep(self._poll_every_s)
                batch = await batches.retrieve(batch.id)
            async for entry in await batches.results(batch.id):
                if entry.custom_id not in chunk:
                    continue
                r = entry.result
                if r.type == "succeeded":
                    self._settle(entry.custom_id, r.message)
                else:
                    error = r.error.error.message if r.type == "errored" else ""
                    self._settle(entry.custom_id, BatchRequestFailed(r.type, error))
        except Exception as exc:
            for cid in chunk:
                self._settle(cid, exc)
        finally:
            for cid in chunk:
                if cid in self._in_flight:
                    self._settle(cid, BatchRequestFailed("missing", "no result returned for this request"))
