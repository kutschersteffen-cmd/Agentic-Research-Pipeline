import test from "node:test";
import assert from "node:assert/strict";
import { oneAtATime } from "../src/lib/useRefetchOnFocus.ts";

test("refetch on focus: a call while one is running is skipped, not stacked", async () => {
  let calls = 0;
  let finish = () => {};
  const run = oneAtATime(() => {
    calls += 1;
    return new Promise<void>((resolve) => (finish = resolve));
  });
  run();
  await Promise.resolve();
  run(); // focus and visibilitychange fire together when the user comes back
  run();
  await Promise.resolve();
  assert.equal(calls, 1);
  finish();
  await new Promise((r) => setTimeout(r, 0));
  run();
  await Promise.resolve();
  assert.equal(calls, 2);
});

test("refetch on focus: a failed call does not block the next one", async () => {
  let calls = 0;
  const run = oneAtATime(() => {
    calls += 1;
    return Promise.reject(new Error("offline"));
  });
  run();
  await new Promise((r) => setTimeout(r, 0));
  run();
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(calls, 2);
});
