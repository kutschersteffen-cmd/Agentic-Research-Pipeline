"""In-memory stand-in for `AsyncAnthropic().messages.batches`, shaped like anthropic 1.13.

Attach as `client._client.messages.batches`. Real SDK types are returned, so the
code under test sees exactly what the API would give it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from anthropic.types import Message, ToolUseBlock, Usage
from anthropic.types.messages import MessageBatch, MessageBatchIndividualResponse


def prompt_of(params: dict) -> str:
    """The first user turn's text, which is what tests key behaviour on."""
    content = params["messages"][0]["content"]
    return content if isinstance(content, str) else content[-1]["text"]


def echo_message(params: dict) -> Message:
    """Default reply: calls emit_result with {"echo": <prompt>}."""
    return Message(
        id="msg_batch",
        type="message",
        role="assistant",
        model=params["model"],
        content=[ToolUseBlock(type="tool_use", id="tu_1", name="emit_result", input={"echo": prompt_of(params)})],
        stop_reason="tool_use",
        stop_sequence=None,
        usage=Usage(input_tokens=10, output_tokens=5),
    )


class FakeBatches:
    """Knobs (set them before or during a test):

    - `hold`: batches stay `in_progress` until `release()` (or `hold = False`).
    - `reverse`: results stream back in reverse submission order.
    - `outcomes`: {custom_id or prompt text: "errored" | "expired" | "canceled"}.
    - `create_error`: raised by the next `create`, then cleared.
    - `stream_delay`: seconds the results stream sleeps between entries (yields to the loop).
    - `retrieve_error`: raised by the next `retrieve`, then cleared.
    - `respond`: params -> Message for succeeded requests.
    """

    def __init__(self) -> None:
        self.hold = False
        self.reverse = False
        self.outcomes: dict[str, str] = {}
        self.create_error: BaseException | None = None
        self.respond = echo_message
        self.creates: list[list[dict]] = []  # the `requests` of every create, in order
        self.retrieve_error: BaseException | None = None
        self.stream_delay = 0.0
        self.retrieves = 0
        self.cancels: list[str] = []
        self._batches: dict[str, dict] = {}  # id -> {"requests", "status"}

    def release(self) -> None:
        self.hold = False

    def _batch(self, batch_id: str, advance: bool = True) -> MessageBatch:
        now = datetime.now(UTC)
        status = self._batches[batch_id]["status"]
        if advance and status != "ended" and not self.hold:
            status = self._batches[batch_id]["status"] = "ended"
        return MessageBatch(
            id=batch_id,
            type="message_batch",
            created_at=now,
            expires_at=now,
            processing_status=status,
            request_counts={"canceled": 0, "errored": 0, "expired": 0, "processing": 0, "succeeded": 0},
            results_url=f"https://fake/{batch_id}/results" if status == "ended" else None,
        )

    async def create(self, *, requests) -> MessageBatch:
        if self.create_error is not None:
            err, self.create_error = self.create_error, None
            raise err
        requests = list(requests)
        self.creates.append(requests)
        batch_id = f"msgbatch_{len(self.creates)}"
        self._batches[batch_id] = {"requests": requests, "status": "in_progress"}
        return self._batch(batch_id, advance=False)  # like the API: never ended on create

    async def retrieve(self, message_batch_id: str) -> MessageBatch:
        self.retrieves += 1
        if self.retrieve_error is not None:
            err, self.retrieve_error = self.retrieve_error, None
            raise err
        return self._batch(message_batch_id)

    async def cancel(self, message_batch_id: str) -> MessageBatch:
        self.cancels.append(message_batch_id)
        entry = self._batches[message_batch_id]
        entry["status"] = "ended"
        for req in entry["requests"]:
            self.outcomes.setdefault(req["custom_id"], "canceled")
        return self._batch(message_batch_id)

    async def results(self, message_batch_id: str):
        # Like the SDK: awaiting `results()` gives an async iterable of entries.
        entry = self._batches[message_batch_id]
        assert entry["status"] == "ended", "results requested before the batch ended"
        requests = list(reversed(entry["requests"])) if self.reverse else entry["requests"]

        async def stream():
            for i, req in enumerate(requests):
                if i and self.stream_delay:
                    await asyncio.sleep(self.stream_delay)
                yield MessageBatchIndividualResponse.model_validate({"custom_id": req["custom_id"], "result": self._result(req)})

        return stream()

    def _result(self, req: dict) -> dict:
        kind = self.outcomes.get(req["custom_id"]) or self.outcomes.get(prompt_of(req["params"]), "succeeded")
        if kind == "succeeded":
            return {"type": "succeeded", "message": self.respond(req["params"]).model_dump()}
        if kind == "errored":
            return {"type": "errored", "error": {"type": "error", "error": {"type": "api_error", "message": "fake failure"}}}
        return {"type": kind}
