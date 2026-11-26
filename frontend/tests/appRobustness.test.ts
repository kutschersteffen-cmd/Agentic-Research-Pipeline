import test from "node:test";
import assert from "node:assert/strict";
import { safeDecode } from "../src/lib/nav.ts";
import { runItem } from "../src/lib/commandPalette.ts";
import { latestGate, memoUntilRejected } from "../src/lib/latest.ts";
import { randomId } from "../src/lib/randomId.ts";
import { wasmBytes } from "../src/lib/wasmFetch.ts";
import { activityOptions } from "../src/lib/themeBuilder.ts";
import { runTypeLabel } from "../src/lib/runs.ts";

// app-robustness slice 1 (docs/superpowers/specs/2026-11-24-app-robustness.md).
const M = (run_id: string, run_type: string) => ({ run_id, run_type }) as never;

test("safeDecode keeps a malformed sequence and still decodes a good one", () => {
  assert.equal(safeDecode("%E0"), "%E0");
  assert.equal(safeDecode("100%"), "100%");
  assert.equal(safeDecode("a%20b"), "a b");
  assert.equal(safeDecode("Grid%2FStorage"), "Grid/Storage");
});

test("runItem: a run without a review screen opens its own row in Run History", () => {
  assert.equal(runItem(M("es 1", "emerging_themes")).href, "#/history/es%201");
  assert.equal(runItem(M("x1", "extraction")).href, "#/review/extraction/x1");
  assert.equal(runItem(M("v1", "proxy_voting")).href, "#/voting/v1");
  const r = runItem(M("es1", "emerging_themes"));
  assert.equal(r.label, `${runTypeLabel("emerging_themes")} es1`);
  assert.equal(r.hint, "Run");
});

test("latestGate: only the newest check stays true, gates are independent", () => {
  const g = latestGate();
  const a = g.next();
  const b = g.next();
  assert.deepEqual([a(), b()], [false, true]);
  const g1 = latestGate(), g2 = latestGate();
  const c = g1.next();
  g2.next();
  assert.equal(c(), true);
});

test("memoUntilRejected shares a result and forgets a failure", async () => {
  let n = 0;
  const f = memoUntilRejected(async () => (++n, "m"));
  assert.deepEqual([await f(), await f()], ["m", "m"]);
  assert.equal(n, 1);
  let k = 0;
  const h = memoUntilRejected(async () => {
    if (++k === 1) throw new Error("x");
    return "m";
  });
  await assert.rejects(h(), { message: "x" });
  assert.equal(await h(), "m");
  assert.equal(k, 2);
});

test("randomId does not need crypto.randomUUID", () => {
  const original = globalThis.crypto.randomUUID;
  Object.defineProperty(globalThis.crypto, "randomUUID", { value: undefined, configurable: true });
  try {
    const [a, b] = [randomId(), randomId()];
    assert.match(a, /^[0-9a-f]{32}$/);
    assert.match(b, /^[0-9a-f]{32}$/);
    assert.notEqual(a, b);
  } finally {
    Object.defineProperty(globalThis.crypto, "randomUUID", { value: original, configurable: true });
  }
});

test("wasmBytes rejects a failed download and passes the bytes of a good one", async () => {
  await assert.rejects(wasmBytes(new Response("<html>", { status: 404 })), { message: "the rule engine could not be downloaded (HTTP 404)" });
  assert.equal((await wasmBytes(new Response(new Uint8Array([0, 97, 115, 109])))).byteLength, 4);
});

test("activityOptions: the theme's activities, else the distinct ones in the results", () => {
  const rows = [
    { activity_id: "a2", activity_name: "Storage" },
    { activity_id: "a1", activity_name: "Grid" },
    { activity_id: "a2", activity_name: "Storage" },
  ];
  assert.deepEqual(activityOptions(null, rows), [{ id: "a2", name: "Storage" }, { id: "a1", name: "Grid" }]);
  assert.deepEqual(activityOptions({ activities: [{ activity_id: "a1", name: "Grid" }] }, [{ activity_id: "a9", activity_name: "Other" }]), [{ id: "a1", name: "Grid" }]);
});
