import { test } from "node:test";
import assert from "node:assert/strict";
import { argusRows, filterRows, tiles, waiting } from "../src/lib/argusStart.ts";
import type { ReviewItem, RunManifest } from "../src/types.ts";

const run = (r: Partial<RunManifest>): RunManifest =>
  ({ run_id: "x", run_type: "extraction", status: "running", created_at: "2026-10-01", updated_at: "2026-10-01", params: {}, company_count: 3,
    completed_count: 0, failed_count: 0, review_count: 0, input_tokens: 0, output_tokens: 0, estimated_cost_usd: 0, ...r }) as RunManifest;
const item = (run_id: string, kind = "value"): ReviewItem => ({ run_id, kind, item_key: `${run_id}:${Math.random()}` }) as unknown as ReviewItem;

const R1 = run({ run_id: "r1", status: "running", created_at: "2026-10-01", params: { schema_name: "Green capex", schema_version: "s1:v2", started_by: "alice" } });
const R2 = run({ run_id: "r2", run_type: "financials", status: "completed", review_count: 2, created_at: "2026-10-02", params: { started_by: "bob" } });

test("rows are Argus runs only, newest first, labelled and stepped", () => {
  const rows = argusRows([R1, R2, run({ run_id: "t", run_type: "theme", status: "completed", created_at: "2026-10-03" })], [item("r2")]);
  assert.deepEqual(rows.map((r) => [r.runId, r.label, r.step, r.status, r.startedBy, r.companies]), [
    ["r2", "Financials", 5, "Needs you", "bob", 3],
    ["r1", "Green capex v2", 4, "Running", "alice", 3],
  ]);
  assert.deepEqual(rows.map((r) => r.openHref), ["#/review", "#/extraction/extract"]);
});

test("cancelled is Stopped, failed is Failed, finished without review is Finished; old transition_plan runs list", () => {
  const rows = argusRows([
    run({ run_id: "a", status: "cancelled", created_at: "1" }),
    run({ run_id: "b", status: "failed", created_at: "2" }),
    run({ run_id: "c", run_type: "tnfd", status: "partially_completed", created_at: "3" }),
    run({ run_id: "d", run_type: "transition_plan", status: "completed", created_at: "4" }),
    run({ run_id: "e", status: "pending", created_at: "5" }),
  ], []);
  assert.deepEqual(rows.map((r) => [r.runId, r.label, r.step, r.status]), [
    ["e", "Extraction", 4, "Running"],
    ["d", "Transition Plan", 5, "Finished"],
    ["c", "TNFD", 5, "Finished"],
    ["b", "Extraction", 4, "Failed"],
    ["a", "Extraction", 4, "Stopped"],
  ]);
});

test("a run without started_by shows null and is hidden by Only mine", () => {
  const rows = argusRows([run({ run_id: "old" }), R1], []);
  assert.equal(rows.find((r) => r.runId === "old")!.startedBy, null);
  assert.deepEqual(filterRows(rows, { step: null, mineOf: "alice" }).map((r) => r.runId), ["r1"]);
});

test("filterRows by step and by mine", () => {
  const rows = argusRows([R1, R2], []);
  assert.deepEqual(filterRows(rows, { step: null, mineOf: null }).map((r) => r.runId), ["r2", "r1"]);
  assert.deepEqual(filterRows(rows, { step: 4, mineOf: null }).map((r) => r.runId), ["r1"]);
  assert.deepEqual(filterRows(rows, { step: null, mineOf: "bob" }).map((r) => r.runId), ["r2"]);
  assert.deepEqual(filterRows(rows, { step: 4, mineOf: "bob" }), []);
});

test("waiting counts only items of Argus rows and leaves empty groups out", () => {
  const rows = argusRows([R1, R2], []);
  assert.deepEqual(waiting(rows, [item("r2"), item("r2"), item("stewardiq_run")]), { total: 2, groups: [{ label: "Values to review", count: 2 }] });
  assert.deepEqual(waiting(filterRows(rows, { step: null, mineOf: "alice" }), [item("r2"), item("r2")]), { total: 0, groups: [] });
});

test("waiting groups documents and errors", () => {
  const rows = argusRows([R2, run({ run_id: "f", status: "failed" })], []);
  assert.deepEqual(waiting(rows, [item("r2"), item("r2", "quarantined_document")]), {
    total: 3,
    groups: [{ label: "Values to review", count: 1 }, { label: "Documents to check", count: 1 }, { label: "Errors", count: 1 }],
  });
});

test("tiles: five steps, step 5 reads '2 values need you', others null; empty input gives five zeros", () => {
  const t = tiles(argusRows([R1, R2], []), [item("r2"), item("r2"), item("other")]);
  assert.deepEqual(t.map((x) => [x.step, x.label, x.count, x.needs]), [
    [1, "Companies", 0, null], [2, "Documents", 0, null], [3, "Schema", 0, null], [4, "Extract", 1, null], [5, "Results", 1, "2 values need you"],
  ]);
  assert.deepEqual(tiles([], []).map((x) => [x.count, x.needs]), [[0, null], [0, null], [0, null], [0, null], [0, null]]);
  assert.equal(tiles(argusRows([run({ status: "failed" })], []), [])[3].needs, "1 failed");
});

test("a running run with review items stays Running at step 4 and its items still count", () => {
  const rows = argusRows([run({ run_id: "r", status: "running", review_count: 1 })], [item("r")]);
  assert.deepEqual([rows[0].step, rows[0].status], [4, "Running"]);
  assert.equal(waiting(rows, [item("r")]).total, 1);
  assert.equal(tiles(rows, [item("r")])[4].needs, null);
});

test("a finished run leaves Needs you once none of its items is open, whatever review_count says", () => {
  const done = run({ run_id: "d", status: "completed", review_count: 4 });
  assert.equal(argusRows([done], [])[0].status, "Finished");
  assert.equal(argusRows([done], [item("d")])[0].status, "Needs you");
});

test("rows show the starter's name and filter on the starter's id; old runs fall back to the id", () => {
  const rows = argusRows([run({ run_id: "n", params: { started_by: "u-1", started_by_name: "Alice Smith" } }), run({ run_id: "o", params: { started_by: "bob" } })], []);
  assert.deepEqual(rows.map((r) => [r.runId, r.starterName]), [["n", "Alice Smith"], ["o", "bob"]]);
  assert.deepEqual(filterRows(rows, { step: null, mineOf: "u-1" }).map((r) => r.runId), ["n"]);
});
