import { test } from "node:test";
import assert from "node:assert/strict";
import { DECISION_STAGES, PROCESSES, WORKSPACES, stepHref, workspaceOfProcess } from "../src/lib/processes.ts";

test("five workspaces, each with at least one process, and process ids unique", () => {
  assert.deepEqual(WORKSPACES.map((w) => w.id), ["stewardiq", "argus", "transitionIntel", "rdLab", "dataHub"]);
  assert.ok(WORKSPACES.every((w) => w.processes.length > 0));
  assert.equal(new Set(PROCESSES.map((p) => p.id)).size, PROCESSES.length);
});

test("a process finds its workspace; old Processes-screen ids still resolve", () => {
  for (const id of ["onboard", "climate", "engage", "proxy", "client", "thematic", "strategy"]) assert.ok(workspaceOfProcess(id), id);
  assert.equal(workspaceOfProcess("extract")?.id, "argus");
  assert.equal(workspaceOfProcess("nope"), undefined);
});

test("stewardship decisions are counted once per stage, never for the ballot stage", () => {
  assert.equal(new Set(DECISION_STAGES).size, DECISION_STAGES.length);
  assert.ok(!DECISION_STAGES.includes("voting"), "ballots are counted on the Proxy Voting runs");
  assert.ok(["monitoring", "selection", "drafting", "checkpoint", "tracking"].every((s) => DECISION_STAGES.includes(s)));
});

test("a step links to its screen and sub-screen", () => {
  assert.equal(stepHref({ tab: "portfolio-monitoring", sub: "holdings", label: "", does: "" }), "#/portfolio-monitoring/holdings");
  assert.equal(stepHref({ tab: "review", label: "", does: "" }), "#/review");
});

test("Argus runs the universe step and the XBRL process", () => {
  const argus = WORKSPACES.find((w) => w.id === "argus")!;
  assert.deepEqual(argus.processes.map((p) => p.id), ["extract", "xbrl"]);
  assert.equal(workspaceOfProcess("xbrl")?.id, "argus");
  assert.equal(stepHref(argus.processes[0].steps[0]), "#/argusUniverse");
  assert.ok(argus.runTypes.includes("xbrl_fetch"));
  assert.equal(WORKSPACES.find((w) => w.runTypes.includes("xbrl_fetch"))?.id, "argus");
  const links = argus.screens.map(([href]) => href);
  assert.ok(links.includes("#/argusUniverse") && links.includes("#/xbrl"));
  const xbrl = argus.processes[1];
  assert.deepEqual(xbrl.steps.map((s) => s.label), ["Universe", "Fetch", "Facts", "Verify"]);
  assert.deepEqual(xbrl.steps.map((s) => s.tab), ["argusUniverse", "xbrl", "xbrl", "xbrl"]);
  assert.deepEqual(xbrl.steps[1].runTypes, ["xbrl_fetch"]);
});
