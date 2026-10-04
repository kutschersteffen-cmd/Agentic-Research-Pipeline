import test from "node:test";
import assert from "node:assert/strict";
import {
  autoContinueDue, docRows, extractInputs, flagReason, pendingOnboard, flowReducer, initialFlow, latestExtractRun, mergeCompanies,
  editedText, matchesTile, reviewCounts, runEndedAt, runScope, stageInput, valueOrigin,
} from "../src/lib/stagedFlow.ts";
import type { FlowAction, FlowState, StageOutput } from "../src/lib/stagedFlow.ts";
import type { CompanyRef, DiscoveryCompanyResult, ReviewDecision, RunManifest } from "../src/types.ts";

const run = (s: FlowState, ...as: FlowAction[]) => as.reduce(flowReducer, s);
const out = (path: string, count: number, companies?: CompanyRef[]): StageOutput => (companies ? { path, count, companies } : { path, count });
const co = (id: string): CompanyRef => ({ company_id: id, name: id });
const dec = (decision: ReviewDecision["decision"]): ReviewDecision => ({ item_key: "k", decision, decided_at: "" });
const manifest = (status: RunManifest["status"], company_count: number) =>
  ({ status, company_count, updated_at: "2026-01-01T00:00:00Z" }) as RunManifest;
const disc = (id: string, n: number, extra: Partial<DiscoveryCompanyResult> = {}) =>
  ({ company_id: id, name: id, documents_found: Array(n).fill({}), homepage_unreachable: false, ...extra }) as unknown as DiscoveryCompanyResult;
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
  const s = run({ ...initialFlow, identify: done, documents: { ...done, runId: "b" }, extractRuns: { financials: "e" } }, started);
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

const twoRuns: FlowAction[] = [
  { type: "extractStarted", job: "financials", runId: "r1" },
  { type: "extractStarted", job: "tnfd", runId: "r2" },
];

test("extract runs per job", () => {
  const s = run(initialFlow, ...twoRuns);
  assert.deepEqual(s.extractRuns, { financials: "r1", tnfd: "r2" });
  assert.deepEqual(s.runIds.slice(-2), ["r1", "r2"]);
});

test("jobsChanged drops removed jobs", () => {
  const before = run(initialFlow, started, finish(0), ...twoRuns);
  const s = run(before, { type: "jobsChanged", jobIds: ["tnfd"] });
  assert.deepEqual(s.extractRuns, { tnfd: "r2" });
  assert.equal(s.identify, before.identify);
});

test("latestExtractRun", () => {
  assert.equal(latestExtractRun(initialFlow), null);
  assert.equal(latestExtractRun(run(initialFlow, ...twoRuns)), "r2");
  assert.equal(latestExtractRun(run(initialFlow, ...twoRuns, { type: "jobsChanged", jobIds: ["financials"] })), "r1");
});

test("stale with any run", () => {
  const s = run(initialFlow, { type: "extractStarted", job: "tnfd", runId: "r2" }, started);
  assert.equal(s.extractStale, true);
});

test("extractRestarted keeps stale; extractStarted clears it", () => {
  const stale = run(initialFlow, { type: "extractStarted", job: "tnfd", runId: "r2" }, started);
  const s = run(stale, { type: "extractRestarted", job: "tnfd", runId: "r3" });
  assert.equal(s.extractStale, true);
  assert.deepEqual(s.extractRuns, { tnfd: "r3" });
  assert.deepEqual(s.runIds, [...stale.runIds, "r3"]);
  assert.equal(run(s, { type: "extractStarted", job: "tnfd", runId: "r4" }).extractStale, false);
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

test("docRows flags only empty companies", () => {
  const rows = docRows([co("a"), co("b")], [disc("a", 0), disc("b", 0)], { a: 2 }, new Set());
  assert.equal(rows[0].flagged, false);
  assert.equal(rows[1].flagged, true);
});

test("docRows keeps companies with no discovery result", () => {
  const rows = docRows([co("a"), co("b"), co("c")], [disc("a", 3)], { b: 1, c: 0 }, new Set(["b"]));
  assert.deepEqual(rows.map((r) => [r.companyId, r.discovered, r.onFile, r.flagged]),
    [["a", 3, 3, false], ["b", 0, 1, false], ["c", 0, 0, true]]);
  assert.equal(rows[1].uploaded, true);
  assert.equal(flagReason(rows[2]), "No discovery result");
});

test("flagReason reads the crawl diagnostics", () => {
  const [down, nohome, used] = docRows([co("a"), co("b"), co("c")], [
    disc("a", 0, { homepage_unreachable: true, crawl_error: "timeout" }),
    disc("b", 0, { homepage_used: null }),
    disc("c", 0, { homepage_used: "https://c.com" }),
  ], {}, new Set());
  assert.equal(flagReason(down), "Site unreachable: timeout");
  assert.equal(flagReason(nohome), "No documents · no homepage known");
  assert.equal(flagReason(used), "No documents found on https://c.com");
});

test("recheck with nothing to onboard keeps stages", () => {
  const s = run(initialFlow, { type: "companies", output: out("all.csv", 50) }, { type: "recheckReady", on: true },
    { type: "readiness", ready: out("ready.csv", 50), onboard: out("onb.csv", 0) });
  assert.equal(s.identify.state, "idle");
  assert.equal(s.documents.state, "idle");
});

test("useAnyway needs an output", () => {
  const s = run({ ...initialFlow, documents: { ...initialFlow.documents, state: "stale" } },
    { type: "useAnyway", stage: "documents" });
  assert.equal(s.documents.state, "stale");
});

test("a stale running stage stays stale when its run finishes", () => {
  const s = run(initialFlow, started, { type: "companies", output: out("n.csv", 1) }, finish(2));
  assert.equal(s.identify.state, "stale");
  assert.equal(s.identify.flagged, 2);
  assert.equal(s.identify.note, "2 companies need review");
});

test("runFinished notes", () => {
  assert.equal(run(initialFlow, started, finish(2, 1)).identify.note, "2 need review · 1 failed");
  assert.equal(run(initialFlow, started, finish(0, 3)).identify.note, "3 failed");
  const c = run(initialFlow, started, { type: "runFinished", stage: "identify", status: "completed", flagged: 0, failed: 0, note: "Couldn't check documents" });
  assert.equal(c.identify.state, "review");
  assert.equal(c.identify.note, "Couldn't check documents");
});

test("pendingOnboard counts the share not yet handed over", () => {
  assert.equal(pendingOnboard(withReady), 0); // both stages skipped
  const s = run(initialFlow, { type: "companies", output: out("all.csv", 50) },
    { type: "readiness", ready: out("ready.csv", 32), onboard: out("onb.csv", 18) });
  assert.equal(pendingOnboard(s), 18);
  assert.equal(pendingOnboard(run(s, { type: "handedOver", stage: "identify", output: out("i", 18) },
    { type: "handedOver", stage: "documents", output: out("d", 17) })), 0);
});

test("recheck un-skips auto-skipped stages", () => {
  const s = run(initialFlow, { type: "companies", output: out("all.csv", 50) },
    { type: "readiness", ready: out("ready.csv", 50), onboard: out("onb.csv", 0) },
    { type: "recheckReady", on: true });
  assert.equal(s.identify.state, "idle");
  assert.equal(s.documents.state, "idle");
  assert.equal(stageInput(s, "identify")?.path, "all.csv");
});

test("leaving skip clears note", () => {
  const s = run(initialFlow, { type: "companies", output: out("all.csv", 5) },
    { type: "readiness", ready: out("r", 5), onboard: out("o", 0) },
    { type: "setHandover", stage: "identify", handover: "skip" },
    { type: "setHandover", stage: "identify", handover: "manual" });
  assert.equal(s.identify.state, "idle");
  assert.equal(s.identify.note, null);
});

test("matchesTile follows the tile semantics", () => {
  const d = (decision: ReviewDecision["decision"], value?: unknown) =>
    ({ item_key: "k", decision, decided_at: "t", edited_value: value === undefined ? null : { value } }) as ReviewDecision;
  assert.equal(matchesTile(null, false), true);
  assert.equal(matchesTile("flagged", true, d("approve")), true);
  assert.equal(matchesTile("flagged", false), false);
  assert.equal(matchesTile("pending", true), true);
  assert.equal(matchesTile("pending", true, d("reject")), false);
  assert.equal(matchesTile("pending", false), false);
  assert.equal(matchesTile("edited", true, d("edit")), true);
  assert.equal(matchesTile("approved", true, d("edit")), false);
  assert.equal(matchesTile("rejected", true), false);
  assert.equal(editedText(d("edit", 5)), "5");
  assert.equal(editedText(d("approve")), undefined);
});

test("jobsChanged keeps stale while a run survives, clears it when none does", () => {
  const stale = run(initialFlow, ...twoRuns, started);
  assert.equal(stale.extractStale, true);
  assert.equal(run(stale, { type: "jobsChanged", jobIds: ["financials", "custom:2"] }).extractStale, true);
  assert.equal(run(stale, { type: "jobsChanged", jobIds: ["custom:2"] }).extractStale, false);
});

test("staleCleared clears the stale flag only", () => {
  const stale = run(initialFlow, ...twoRuns, started);
  const s = run(stale, { type: "staleCleared" });
  assert.equal(s.extractStale, false);
  assert.deepEqual(s.extractRuns, stale.extractRuns);
});

test("restarts while stale are remembered as fresh; new staleness resets them", () => {
  const stale = run(initialFlow, ...twoRuns, started);
  const s = run(stale, { type: "extractRestarted", job: "financials", runId: "r3" });
  assert.deepEqual(s.freshJobs, ["financials"]);
  assert.equal(s.extractStale, true);
  assert.deepEqual(run(s, started).freshJobs, []);
  assert.deepEqual(run(s, { type: "staleCleared" }).freshJobs, []);
  assert.deepEqual(run(s, { type: "jobsChanged", jobIds: ["tnfd"] }).freshJobs, []);
  assert.deepEqual(run(initialFlow, ...twoRuns, { type: "extractRestarted", job: "tnfd", runId: "r9" }).freshJobs, []);
});

test("correct reads like edit", () => {
  const d = { item_key: "k", decision: "correct", corrected_value: { value: 5 }, decided_at: "" } as ReviewDecision;
  assert.equal(editedText(d), "5");
  assert.equal(reviewCounts(0, [d], 0).edited, 1);
});
