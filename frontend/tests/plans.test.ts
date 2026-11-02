import test from "node:test";
import assert from "node:assert/strict";
import { resultHref, stepRows, type Plan, type PlanCall } from "../src/lib/plans.ts";

const call = (seq: number, over: Partial<PlanCall> = {}): PlanCall =>
  ({ seq, kind: "extraction", params: {}, status: "done", run_id: null, result_ref: null, ...over });

const plan = (calls: PlanCall[]): Plan => ({
  id: "plan_1", brief: "b", script: "s", status: "running", approved_by: "a", approved_at: null, error: null,
  dry_run: [1, 2, 3].map((seq) => ({ seq, kind: "extraction", params: {}, depends_on: null })), calls,
});

test("steps not reached yet are pending; reached ones carry the stored status", () => {
  const rows = stepRows(plan([call(1), call(2, { status: "awaiting_review" })]));
  assert.deepEqual(rows.map((r) => r.status), ["done", "awaiting_review", "pending"]);
});

test("calls beyond the dry run (a data-dependent loop) are listed too", () => {
  assert.equal(stepRows(plan([call(1), call(2), call(3), call(4)])).length, 4);
});

test("a step links to its run, or to the screen of a run-less result", () => {
  assert.equal(resultHref(call(1, { run_id: "run_a b" })), "#/history/run_a%20b");
  assert.equal(resultHref(call(1, { result_ref: "report:rep_1" })), "#/reporting");
  assert.equal(resultHref(call(1, { result_ref: "decision:run_x" })), "#/decision");
  assert.equal(resultHref(call(1, { result_ref: "index:plan_index@2026-10-31" })), "#/index");
  assert.equal(resultHref(call(1)), null);
});
