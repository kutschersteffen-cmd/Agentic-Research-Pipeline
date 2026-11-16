import test from "node:test";
import assert from "node:assert/strict";
import { oneAtATime, onReturn } from "../src/lib/useRefetchOnFocus.ts";

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

test("AC-50 wiring: focus or a visible tab refetches once, a hidden tab and an unsubscribed page do not", async () => {
  const win = new EventTarget();
  const doc = Object.assign(new EventTarget(), { hidden: false });
  let calls = 0;
  let finish = () => {};
  const stop = onReturn(win, doc, () => {
    calls += 1;
    return new Promise<void>((resolve) => (finish = resolve));
  });
  const settle = () => new Promise((r) => setTimeout(r, 0));
  win.dispatchEvent(new Event("focus"));
  doc.dispatchEvent(new Event("visibilitychange")); // both fire when the user comes back
  await settle();
  assert.equal(calls, 1);
  finish();
  await settle();
  doc.hidden = true;
  doc.dispatchEvent(new Event("visibilitychange")); // leaving the tab
  await settle();
  assert.equal(calls, 1);
  doc.hidden = false;
  doc.dispatchEvent(new Event("visibilitychange"));
  await settle();
  assert.equal(calls, 2);
  finish();
  await settle();
  stop();
  win.dispatchEvent(new Event("focus"));
  await settle();
  assert.equal(calls, 2);
});
