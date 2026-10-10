import test from "node:test";
import assert from "node:assert/strict";
import { batchWaitText } from "../src/lib/runs.ts";

test("wait line", () => {
  const at = new Date(2026, 9, 10, 14, 2).toISOString(); // local 14:02
  const wait = { batch_id: "b1", request_count: 38412, submitted_at: at, status: "in_progress" };
  assert.equal(
    batchWaitText(wait),
    "Waiting on batch · 38,412 requests · submitted 14:02 · Anthropic usually finishes within an hour",
  );
});
