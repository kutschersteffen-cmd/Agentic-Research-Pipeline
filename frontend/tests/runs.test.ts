import test from "node:test";
import assert from "node:assert/strict";
import { canResumeRun, compareSince, hasFailureDetails, needsAttentionRuns, resumableFailedRuns, resumeSummary } from "../src/lib/runs.ts";
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

test("compareSince puts undated rows after dated ones, oldest dated first", () => {
  const rows = [null, "2026-10-17T10:00:00Z", null, "2026-10-12T10:00:00Z"];
  assert.deepEqual([...rows].sort(compareSince), ["2026-10-12T10:00:00Z", "2026-10-17T10:00:00Z", null, null]);
});

test("hasFailureDetails is true only for failed and partially_completed", () => {
  for (const s of ["failed", "partially_completed"]) assert.equal(hasFailureDetails(s), true, s);
  for (const s of ["completed", "running", "pending", "cancelled", ""]) assert.equal(hasFailureDetails(s), false, s);
});

test("resumableFailedRuns keeps failed and partially_completed resumable runs in order", () => {
  const u = ago(MIN);
  const runs = [run("extraction", "failed", u), run("theme", "partially_completed", u), run("financials", "completed", u), run("holdings", "failed", u)];
  assert.deepEqual(ids(resumableFailedRuns(runs)), [runs[0].run_id, runs[1].run_id]);
});

test("resumeSummary all resumed", () => {
  assert.equal(resumeSummary(2, []), "Resumed 2 of 2.");
});

test("resumeSummary lists refusals in order", () => {
  assert.equal(
    resumeSummary(2, [
      { runId: "A", message: "409: busy" },
      { runId: "B", message: "500: down" },
    ]),
    "Resumed 0 of 2. Refused: A: 409: busy; B: 500: down",
  );
});

test("resumeSummary with one refusal", () => {
  assert.equal(resumeSummary(2, [{ runId: "B", message: "409: busy" }]), "Resumed 1 of 2. Refused: B: 409: busy");
});
