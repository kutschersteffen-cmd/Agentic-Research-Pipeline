import test from "node:test";
import assert from "node:assert/strict";
import { canResumeRun, needsAttentionRuns } from "../src/lib/runs.ts";
import type { RunManifest } from "../src/types.ts";

const RESUMABLE = ["theme", "extraction", "financials", "tnfd", "transition_plan", "identity", "discovery", "xbrl_fetch"];
const NOT_RESUMABLE = ["proxy_voting", "holdings", "emerging_themes", "taxonomy_research", "calibration", "transition_barrier_refresh"];
const now = new Date("2026-10-18T12:00:00Z");
const ago = (ms: number) => new Date(now.getTime() - ms).toISOString();
const MIN = 60 * 1000;
const DAY = 24 * 60 * MIN;
const run = (runType: string, status: string, updatedAt: string) =>
  ({ run_id: `${runType}-${status}-${updatedAt}`, run_type: runType, status, updated_at: updatedAt }) as unknown as RunManifest;
const ids = (runs: RunManifest[]) => runs.map((r) => r.run_id);

test("canResumeRun is true for all 8 resumable types x failed, partially_completed, cancelled", () => {
  for (const t of RESUMABLE) for (const s of ["failed", "partially_completed", "cancelled"]) assert.equal(canResumeRun(t, s), true, `${t} ${s}`);
});

test("canResumeRun is false for resumable types x completed, running, pending", () => {
  for (const t of RESUMABLE) for (const s of ["completed", "running", "pending"]) assert.equal(canResumeRun(t, s), false, `${t} ${s}`);
});

test("canResumeRun is false for proxy_voting, holdings, emerging_themes, taxonomy_research, calibration, transition_barrier_refresh x failed, partially_completed, cancelled", () => {
  for (const t of NOT_RESUMABLE) for (const s of ["failed", "partially_completed", "cancelled"]) assert.equal(canResumeRun(t, s), false, `${t} ${s}`);
});

test("needsAttentionRuns drops cancelled, completed, running, pending", () => {
  const runs = RESUMABLE.flatMap((t) => ["cancelled", "completed", "running", "pending"].map((s) => run(t, s, ago(60 * MIN))));
  assert.deepEqual(needsAttentionRuns(runs, now), []);
});

test("needsAttentionRuns drops non-resumable types", () => {
  const runs = [run("holdings", "failed", ago(60 * MIN)), run("proxy_voting", "partially_completed", ago(60 * MIN))];
  assert.deepEqual(needsAttentionRuns(runs, now), []);
});

test("needsAttentionRuns keeps exactly 14 days, drops 14 days and 1 second", () => {
  const edge = run("theme", "failed", ago(14 * DAY));
  const past = run("theme", "failed", ago(14 * DAY + 1000));
  assert.deepEqual(needsAttentionRuns([edge, past], now), [edge]);
});

test("needsAttentionRuns returns failed and partially_completed in input order", () => {
  const a = run("tnfd", "partially_completed", ago(3 * DAY));
  const b = run("theme", "failed", ago(1 * DAY));
  const c = run("xbrl_fetch", "failed", ago(5 * DAY));
  assert.deepEqual(ids(needsAttentionRuns([a, b, c], now)), ids([a, b, c]));
});

test("needsAttentionRuns drops empty and unparseable updated_at", () => {
  const runs = [run("theme", "failed", ""), run("theme", "failed", "not a date")];
  assert.deepEqual(needsAttentionRuns(runs, now), []);
});

test("needsAttentionRuns keeps a run updated 1 minute after now", () => {
  const future = run("theme", "failed", new Date(now.getTime() + MIN).toISOString());
  assert.deepEqual(needsAttentionRuns([future], now), [future]);
});
