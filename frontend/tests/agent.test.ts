import test from "node:test";
import assert from "node:assert/strict";
import { chipLabel, scriptLines, sendsComposer, threadTitle } from "../src/lib/agent.ts";
import { HUBS, redirectHash } from "../src/lib/nav.ts";

// Agent screen shell (docs/superpowers/specs/2026-11-21-agent-panel-code-mode.md, slice 6).

test("a thread's chip names the status as the spec spells it (AC-27, AC-29)", () => {
  const statuses = ["draft", "approved", "running", "awaiting_review", "done", "failed", "cancelled"];
  assert.deepEqual(statuses.map(chipLabel), ["draft", "approved", "running", "awaiting review", "done", "failed", "cancelled"]);
});

test("a thread's title is the brief's first 60 characters", () => {
  assert.equal(threadTitle("x".repeat(80)), "x".repeat(60));
  assert.equal(threadTitle("short brief"), "short brief");
});

test("the Script tab numbers every line from 1 to the last (AC-29b)", () => {
  const script = 'u = universe_build(taxonomy_id="t", source="s.csv")\n\ne = extraction(universe_run_id=u.run_id, schema_id="x")\n';
  assert.deepEqual(scriptLines(script), [
    { n: 1, text: 'u = universe_build(taxonomy_id="t", source="s.csv")' },
    { n: 2, text: "" },
    { n: 3, text: 'e = extraction(universe_run_id=u.run_id, schema_id="x")' },
  ]);
  assert.deepEqual(scriptLines("one line"), [{ n: 1, text: "one line" }]);
});

test("Enter sends the composer; Shift+Enter and IME composition do not (AC-35)", () => {
  assert.equal(sendsComposer({ key: "Enter", shiftKey: false }), true);
  assert.equal(sendsComposer({ key: "Enter", shiftKey: true }), false);
  assert.equal(sendsComposer({ key: "Enter", shiftKey: false, isComposing: true }), false);
  assert.equal(sendsComposer({ key: "a", shiftKey: false }), false);
});

test("an old plan link opens the same plan on the Agent screen (AC-37)", () => {
  assert.equal(redirectHash("#/plans/p_1"), "#/agent/p_1");
  assert.equal(redirectHash("#/plans"), "#/agent");
  assert.equal(redirectHash("#/plansx"), null);
  assert.equal(redirectHash("#/agent/p_1"), null);
});

test("the Runs group shows Agent and no Research plans (AC-38)", () => {
  const labels = HUBS.find((h) => h.label === "Runs")!.tabs.map(([, label]) => label);
  assert.ok(labels.includes("Agent"));
  assert.ok(!labels.some((l) => /research plans/i.test(l)));
});
