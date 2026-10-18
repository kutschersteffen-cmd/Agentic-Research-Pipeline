import { test } from "node:test";
import assert from "node:assert/strict";
import { compareMessage, cutoffNotice, decisionBlocks, methodNote, windowLabel } from "../src/lib/signals.ts";
import type { SignalComparison } from "../src/types.ts";

const methodOf = (id: string) => (id === "abc123" ? "price_momentum" : "sestm");
const cmp = (c: Partial<SignalComparison>): SignalComparison => ({ a: "abc123", b: "def456", verdict: "a_higher", months: 36, n_comparisons: 3, reason: null, ...c });

test("insufficient data never names a higher, better or winning signal", () => {
  const m = compareMessage(cmp({ verdict: "insufficient_data", n_comparisons: 1 }), methodOf);
  assert.equal(m, "Insufficient data: these signals cannot be separated (36 months, 1 comparison)");
  assert.doesNotMatch(m, /higher|better|winner/i);
});

test("a_higher names A, b_higher names B, singular counts, reason appended", () => {
  assert.equal(compareMessage(cmp({}), methodOf), "price_momentum abc123 is higher (36 months, 3 comparisons)");
  assert.equal(compareMessage(cmp({ verdict: "b_higher", months: 1 }), methodOf), "sestm def456 is higher (1 month, 3 comparisons)");
  assert.equal(compareMessage(cmp({ reason: "thin overlap" }), methodOf), "price_momentum abc123 is higher (36 months, 3 comparisons) thin overlap");
});

test("windowLabel flags only in-window results with a recorded cutoff", () => {
  const label = "contaminated (in the model's training window)";
  assert.equal(windowLabel("in_window", "recorded"), label);
  assert.equal(windowLabel("post_cutoff", "recorded"), null);
  assert.equal(windowLabel("in_window", "none"), null);
  assert.equal(windowLabel("in_window", "unknown"), null);
});

test("cutoffNotice only for an unknown cutoff", () => {
  assert.equal(cutoffNotice("unknown"), "cutoff unknown: not evidence");
  assert.equal(cutoffNotice("recorded"), null);
  assert.equal(cutoffNotice("none"), null);
});

test("decisionBlocks: non-approvers and no role are blocked, unknown cutoff blocks graduate only", () => {
  const need = { graduate: "Requires approver", shelve: "Requires approver" };
  for (const role of ["viewer", "analyst", null] as const) for (const s of ["none", "unknown"] as const) assert.deepEqual(decisionBlocks(role, s), need);
  assert.deepEqual(decisionBlocks("approver", "unknown"), { graduate: "cutoff unknown: not evidence", shelve: null });
  assert.deepEqual(decisionBlocks("approver", "recorded"), { graduate: null, shelve: null });
  assert.deepEqual(decisionBlocks("approver", "none"), { graduate: null, shelve: null });
});

test("methodNote only for methods the app cannot run", () => {
  assert.equal(methodNote({ name: "x", runnable_in_app: false }), "Run from the CLI or a notebook");
  assert.equal(methodNote({ name: "x", runnable_in_app: true }), null);
});
