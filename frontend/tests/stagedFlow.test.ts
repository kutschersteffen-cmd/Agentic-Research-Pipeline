import test from "node:test";
import assert from "node:assert/strict";
import {
  autoContinueDue, companiesToCheck, docRows, extractInputs, flowReducer, initialFlow, mergeCompanies,
  reviewCounts, runEndedAt, runScope, stageInput, valueOrigin,
} from "../src/lib/stagedFlow.ts";
import type { FlowAction, FlowState, StageOutput } from "../src/lib/stagedFlow.ts";
import type { CompanyRef, DiscoveryCompanyResult, ReviewDecision, RunManifest } from "../src/types.ts";

const run = (s: FlowState, ...as: FlowAction[]) => as.reduce(flowReducer, s);
const out = (path: string, count: number, companies?: CompanyRef[]): StageOutput => (companies ? { path, count, companies } : { path, count });
const co = (id: string): CompanyRef => ({ company_id: id, name: id });
const dec = (decision: ReviewDecision["decision"]): ReviewDecision => ({ item_key: "k", decision, decided_at: "" });
const manifest = (status: RunManifest["status"], company_count: number) =>
  ({ status, company_count, updated_at: "2026-01-01T00:00:00Z" }) as RunManifest;
const disc = (id: string, n: number) =>
  ({ company_id: id, name: id, documents_found: Array(n).fill({}) }) as unknown as DiscoveryCompanyResult;
const finish = (flagged: number, failed = 0, status: "completed" | "cancelled" | "failed" = "completed"): FlowAction =>
  ({ type: "runFinished", stage: "identify", status, flagged, failed });
const started: FlowAction = { type: "runStarted", stage: "identify", runId: "r1" };

test("manual clean run waits", () => {
  const s = run(initialFlow, started, finish(0));
  assert.equal(s.identify.state, "ready");
  assert.equal(autoContinueDue(s.identify), false);
});

test("auto clean run is due", () => {
  const s = run(initialFlow, { type: "setHandover", stage: "identify", handover: "auto" }, started, finish(0));
  assert.equal(autoContinueDue(s.identify), true);
});

test("auto with flagged holds", () => {
  const s = run(initialFlow, { type: "setHandover", stage: "identify", handover: "auto" }, started, finish(3));
  assert.equal(s.identify.state, "review");
  assert.equal(s.identify.note, "3 companies need review");
  assert.equal(autoContinueDue(s.identify), false);
});

test("stopped run holds", () => {
  const c = run(initialFlow, started, finish(0, 0, "cancelled"));
  assert.equal(c.identify.state, "review");
  assert.equal(c.identify.note, "Stopped");
  assert.equal(run(initialFlow, started, finish(0, 0, "failed")).identify.state, "failed");
});

test("empty handover holds", () => {
  const s = run(initialFlow, { type: "handedOver", stage: "identify", output: out("x", 0) });
  assert.equal(s.identify.state, "review");
  assert.equal(s.identify.note, "No companies to carry forward");
  assert.equal(s.identify.output, null);
});

test("skip passes input through", () => {
  const s = run(initialFlow,
    { type: "setHandover", stage: "identify", handover: "skip" },
    { type: "companies", output: out("u.csv", 5) });
  assert.deepEqual(stageInput(s, "documents"), { path: "u.csv", count: 5 });
});

test("rerun marks later stages stale", () => {
  const done = { ...initialFlow.identify, state: "done" as const, runId: "a" };
  const s = run({ ...initialFlow, identify: done, documents: { ...done, runId: "b" }, extractRunId: "e" }, started);
  assert.equal(s.documents.state, "stale");
  assert.equal(s.extractStale, true);
});

test("useAnyway clears stale", () => {
  const o = out("d", 2);
  const s = run({ ...initialFlow, documents: { ...initialFlow.documents, state: "stale", output: o } },
    { type: "useAnyway", stage: "documents" });
  assert.equal(s.documents.state, "done");
  assert.equal(s.documents.output, o);
});

test("new companies stale everything", () => {
  const s = run(initialFlow, started, { type: "runStarted", stage: "documents", runId: "r2" },
    { type: "companies", output: out("n.csv", 1) });
  assert.equal(s.identify.state, "stale");
  assert.equal(s.documents.state, "stale");
});

test("new list un-skips auto-skipped stages", () => {
  const s = run(initialFlow,
    { type: "companies", output: out("all.csv", 50) },
    { type: "readiness", ready: out("r", 50), onboard: out("o", 0) },
    { type: "companies", output: out("new.csv", 9) });
  assert.equal(s.identify.state, "idle");
  assert.equal(s.documents.state, "idle");
  assert.equal(s.identify.note, null);
  assert.equal(s.identify.handover, "manual");
});

test("profile change keeps stages", () => {
  const s = run(initialFlow, started, finish(0), { type: "extractStarted", runId: "e" }, { type: "profileChanged" });
  assert.equal(s.extractRunId, null);
  assert.equal(s.identify.state, "ready");
});

const skipBoth: FlowAction[] = [
  { type: "setHandover", stage: "identify", handover: "skip" },
  { type: "setHandover", stage: "documents", handover: "skip" },
];
const withReady = run(initialFlow, ...skipBoth, { type: "companies", output: out("all.csv", 50) },
  { type: "readiness", ready: out("ready.csv", 32), onboard: out("onb.csv", 18) });

test("ready companies skip stages", () => {
  assert.equal(stageInput(withReady, "identify")?.count, 18);
  assert.deepEqual(extractInputs(withReady).map((o) => o.count), [32, 18]);
});

test("recheck sends everyone", () => {
  const s = run(withReady, { type: "recheckReady", on: true });
  assert.equal(stageInput(s, "identify")?.path, "all.csv");
  assert.deepEqual(extractInputs(s).map((o) => o.path), ["all.csv"]);
});

test("failed readiness onboards all", () => {
  const s = run(initialFlow, { type: "companies", output: out("all.csv", 50) },
    { type: "readiness", ready: null, onboard: null });
  assert.equal(stageInput(s, "identify")?.count, 50);
  assert.equal(s.readinessNote, "Couldn't check stored documents; all companies will be onboarded");
});

test("nothing to onboard", () => {
  const s = run(initialFlow, { type: "companies", output: out("all.csv", 50) },
    { type: "readiness", ready: out("ready.csv", 50), onboard: out("onb.csv", 0) });
  assert.equal(s.identify.state, "skipped");
  assert.equal(s.documents.state, "skipped");
  assert.equal(s.identify.note, "Nothing to onboard");
  assert.deepEqual(extractInputs(s).map((o) => o.count), [50]);
});

test("mergeCompanies dedups", () => {
  const [a, b, c] = ["a", "b", "c"].map(co);
  assert.deepEqual(mergeCompanies([out("x", 2, [a, b]), out("y", 2, [b, c])]).map((x) => x.company_id), ["a", "b", "c"]);
});

test("runIds accumulate", () => {
  const s = run(initialFlow, started, { type: "runStarted", stage: "documents", runId: "r2" },
    { type: "extractStarted", runId: "e" });
  assert.equal(s.runIds.length, 3);
});

test("reviewCounts", () => {
  assert.deepEqual(reviewCounts(2, [dec("approve"), dec("edit"), dec("edit"), dec("reject")], 4),
    { pending: 2, approved: 1, edited: 2, rejected: 1, flagged: 4 });
});

test("valueOrigin", () => {
  assert.equal(valueOrigin(undefined), "system");
  assert.equal(valueOrigin(dec("approve")), "system");
  assert.equal(valueOrigin(dec("edit")), "edited");
});

test("runScope and runEndedAt", () => {
  assert.equal(runScope(manifest("completed", 1)), "single");
  assert.equal(runScope(manifest("completed", 50)), "batch");
  assert.equal(runEndedAt(manifest("running", 1)), null);
  assert.equal(runEndedAt(manifest("completed", 1)), "2026-01-01T00:00:00Z");
});

test("companiesToCheck skips companies with documents", () => {
  assert.deepEqual(companiesToCheck([disc("a", 0), disc("b", 2), disc("c", 0)], new Set(["b"])).sort(), ["a", "b", "c"]);
});

test("docRows flags only empty companies", () => {
  const rows = docRows([disc("a", 0), disc("b", 0)], { a: 2 }, new Set());
  assert.equal(rows[0].flagged, false);
  assert.equal(rows[1].flagged, true);
});
