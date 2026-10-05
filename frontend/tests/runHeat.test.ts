import test from "node:test";
import assert from "node:assert/strict";
import { buildRun, stats, formatEta, eta, END, N } from "../src/pages/lab/runHeatData.ts";

test("simulation is deterministic and ends with blocked companies", () => {
  const a = stats(buildRun(), END), b = stats(buildRun(), END);
  assert.deepEqual(a, b);
  assert.ok(a.blocked > 0 && a.done > 0 && a.done + a.blocked <= N);
  assert.deepEqual(stats(buildRun(), 0), { done: 0, retries: 0, blocked: 0 });
});

test("ETA is h:mm", () => {
  assert.equal(formatEta(2918), "48:38");
  assert.equal(formatEta(5), "0:05");
  assert.equal(eta(10, 100, 0, 0), "--");
  assert.equal(eta(END, 0, 3, 0), "holds");
});
