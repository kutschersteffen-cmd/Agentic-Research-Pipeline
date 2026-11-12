import test from "node:test";
import assert from "node:assert/strict";
import { findingText } from "../src/lib/findings.ts";
import { unmatchedEmptyText } from "../src/lib/holdings.ts";
import { WORKSPACES } from "../src/lib/processes.ts";
import { explorerParams } from "../src/lib/valueChain.ts";
import { processState, stepActivity, stepState, stepStatusLine, type Activity } from "../src/lib/workspaceCard.ts";

const step = (process: string, label: string) =>
  WORKSPACES.flatMap((w) => w.processes).find((p) => p.title === process)!.steps.find((s) => s.label === label)!;
const MASTER = step("Map securities to issuers", "Load security master");
const MAP = step("Map securities to issuers", "Map holdings");
const INTAKE = step("Monthly monitoring", "Holdings Intake");
const ALERTS = step("Monthly monitoring", "Monitoring & Alerts");
const load = (feed: string, status: string, at: string) => ({ feed, last_load: { status, at } });
const line = (s: typeof MASTER, activity?: Activity | null) =>
  stepStatusLine(stepState(s, [], null, activity), 0, 0, stepActivity(s, activity)?.at ?? null, "en-GB").text;

test("12a: Security Master's empty row says nothing was loaded when there is no master", () => {
  assert.equal(unmatchedEmptyText(0), "No holdings have been loaded through Holdings Intake yet.");
  assert.equal(unmatchedEmptyText(3), "Every held security is matched.");
});

test("12b: without activity the four steps are idle, as before", () => {  // AC-145
  for (const s of [MASTER, MAP, INTAKE, ALERTS]) {
    assert.equal(stepState(s, [], null), "idle");
    assert.equal(stepState(s, [], null, null), "idle");
    assert.equal(line(s), "No runs yet");
  }
});

test("12b: load steps are done on an ok load, failed when the only loads failed", () => {
  const ok: Activity = {
    feeds: [load("security_master", "ok", "2026-11-10T09:00:00+00:00"), load("holdings", "failed", "2026-11-11T09:00:00+00:00"),
      load("holdings", "ok", "2026-11-09T09:00:00+00:00"), load("index", "ok", "2026-11-12T09:00:00+00:00"), { feed: "holdings", last_load: null }],
    lastRun: null,
  };
  assert.equal(line(MASTER, ok), "Done · 10 Nov");
  assert.equal(line(MAP, ok), "Done · 12 Nov");
  assert.equal(line(INTAKE, ok), "Done · 12 Nov");
  assert.equal(line(ALERTS, ok), "No runs yet");
  const failed: Activity = { feeds: [load("security_master", "failed", "x"), load("holdings", "failed", "x"), { feed: "index", last_load: null }], lastRun: null };
  assert.equal(line(MASTER, failed), "Last run failed");
  assert.equal(line(INTAKE, failed), "Last run failed");
  assert.equal(line(MAP, { feeds: [], lastRun: null }), "No runs yet");
});

test("12b: a process is as far as its steps, so one with a recorded load is not folded away as idle", () => {
  const monitor = WORKSPACES.flatMap((w) => w.processes).find((p) => p.title === "Monthly monitoring")!;
  assert.equal(processState(monitor, [], null), "idle");
  assert.equal(processState(monitor, [], null, { feeds: [load("holdings", "ok", "2026-11-12T09:00:00+00:00")], lastRun: null }), "done");
  assert.equal(processState(monitor, [], null, { feeds: [load("holdings", "failed", "x")], lastRun: null }), "failed");
});

test("12b: Monitoring & Alerts is done once a monthly run ran, never failed", () => {
  assert.equal(line(ALERTS, { feeds: [load("holdings", "failed", "x")], lastRun: { at: "2026-11-12T10:00:00+00:00" } }), "Done · 12 Nov");
  assert.equal(stepActivity(step("Monthly monitoring", "Dashboards"), { feeds: [], lastRun: { at: "x" } }), null);
});

test("12e: findingText", () => {  // AC-151, AC-152
  assert.equal(findingText({ stage: "qa", rule: "invalid_edit", message: "edit changes nothing" }), null);
  assert.equal(findingText({ stage: "qa", rule: "applied", message: "Shortened the headline" }), "Visual check: adjusted. Shortened the headline");
  assert.equal(
    findingText({ stage: "fit", rule: "slot_dropped", message: "Slot 'number_1' does not exist in a/b; its content was dropped." }),
    "Layout: some content did not fit this slide and was left out.",
  );
  assert.equal(findingText({ stage: "lint", rule: "exclamation", message: "Remove the exclamation mark." }), "Wording: Remove the exclamation mark.");
  assert.equal(findingText({ stage: "data", rule: "x", message: "m" }), "Data: m");
  assert.equal(findingText({ stage: "qa", rule: "x", message: "m" }), "Visual check: m");
  assert.equal(findingText({ stage: "new", rule: "x", message: "m" }), "Check: m");
});

test("12f: a view name without a node is the explorer's start", () => {
  for (const view of ["tree", "footprint", "exposure", "shock"]) assert.deepEqual(explorerParams([view]), []);
  assert.deepEqual(explorerParams(["DEU_C29", "tree"]), ["DEU_C29", "tree"]);
  assert.deepEqual(explorerParams(["DEU_C29"]), ["DEU_C29"]);
  assert.deepEqual(explorerParams([]), []);
});
