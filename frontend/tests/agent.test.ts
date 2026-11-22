import test from "node:test";
import assert from "node:assert/strict";
import { budgetLine, chipLabel, lineDiff, scriptLines, sendsComposer, stepState, threadTitle, usd } from "../src/lib/agent.ts";
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

// Stage tabs: Diff and Audit (slice 8).

test("the Diff header counts the - and + lines of diff -u between two script versions (AC-32)", () => {
  const v1 = 'u = universe_build(taxonomy_id="t", source="s.csv")\ne = extraction(universe_run_id=u.run_id, schema_id="x")\nr = report_render(source_ids=[e.run_id])\n';
  const v2 = 'u = universe_build(taxonomy_id="t", source="s.csv")\ne = extraction(universe_run_id=u.run_id, schema_id="y")\nf = financials_extraction(universe_run_id=u.run_id)\nr = report_render(source_ids=[e.run_id])\n';
  const d = lineDiff(v1, v2);
  // diff -u: 1 line removed (schema_id="x"), 2 added (schema_id="y" and the financials step).
  assert.deepEqual([d.removed, d.added], [1, 2]);
  assert.deepEqual(d.lines.map((l) => l.op).join(""), " -++ ");
  assert.equal(d.lines[1].text, 'e = extraction(universe_run_id=u.run_id, schema_id="x")');
});

test("the line diff of equal scripts, and of a missing final newline, matches diff -u", () => {
  assert.deepEqual(lineDiff("a\nb\n", "a\nb\n"), { removed: 0, added: 0, lines: [{ op: " ", text: "a" }, { op: " ", text: "b" }] });
  // diff -u marks a last line that lost its newline as changed.
  assert.deepEqual([lineDiff("a\nb\n", "a\nb").removed, lineDiff("a\nb\n", "a\nb").added], [1, 1]);
  assert.deepEqual([lineDiff("", "a\n").removed, lineDiff("", "a\n").added], [0, 1]);
});

test("a step reads started once called, skipped when the plan ended without it, else planned", () => {
  assert.equal(stepState("running", true), "started");
  assert.equal(stepState("running", false), "planned");
  assert.equal(stepState("failed", false), "planned"); // a resume can still run it
  assert.equal(stepState("done", false), "skipped");
  assert.equal(stepState("cancelled", false), "skipped");
});

test("the Audit tab shows a cost as the API serves it (AC-33)", () => {
  assert.equal(usd(1.2), "$1.20");
  assert.equal(usd(0), "$0.00");
  assert.equal(usd(0.123456), "$0.123456");
  assert.equal(usd(null), "–");
  assert.equal(budgetLine(2.05, 5), "spent $2.05 of $5.00");
  assert.equal(budgetLine(2.05, null), "spent $2.05, no budget set");
});
