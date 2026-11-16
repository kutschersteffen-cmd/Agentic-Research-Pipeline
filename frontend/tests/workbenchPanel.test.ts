import test from "node:test";
import assert from "node:assert/strict";
import { LAST_LINE, PANEL_TABS, neighbour, partValue, rankOf, why } from "../src/lib/workbenchPanel.ts";
import type { WorklistRow } from "../src/types.ts";

const part = (id: string, weight: number, normalised: number, empty = false) => ({ id, weight, normalised, points: Math.round(weight * normalised * 10) / 10, empty });

function row(id: string, score: number, over: Partial<WorklistRow> = {}): WorklistRow {
  return {
    issuer_id: id, company: `Company ${id}`, sector: "Energy", identifier: id,
    engaged: { yes: false, last: null }, last_topics: [], programmes: [], norms_violation: null,
    equity_held_eur_m: 1, ownership_pct: null, holdings_weight_pct: 1, aum_held_eur_m: 1,
    coverage_tier: "letter", coverage_tier_confirmed: true,
    triggers: { high: 0, medium: 0, low: 0 }, open_engagements: 0, escalated: 0, overdue_commitments: 0,
    broken_commitments: 0, commitment_flags: [], new_high_trigger: false,
    next_meeting: null, transition_grade: null, esg_score: null, controversy: null, carbon_intensity: null, esg_extra: {},
    score, parts: [], selection: null, held_in: [], selected_elsewhere: [], notes: { count: 0, latest: null },
    ...over,
  };
}

test("AC-91: the seven tabs, in the spec's order", () => {
  assert.deepEqual([...PANEL_TABS], ["Why", "Company", "Engagements", "Votes", "Triggers", "Holdings", "Notes"]);
});

test("AC-23, AC-41, AC-61, AC-40: the Why tab's fixed wording, total and Simulated values", () => {
  const shell = row("S", 34.0, {
    company: "Shell plc",
    triggers: { high: 1, medium: 1, low: 0 },
    holdings_weight_pct: 1.204,
    escalated: 1,
    transition_grade: { value: "E", label: "Not credible", simulated: true },
    esg_score: { value: 3.9, simulated: true },
    parts: [part("open_triggers", 30, 0.8), part("escalated", 10, 1), part("next_meeting", 5, 0, true), part("esg_score", 0, 0.4), part("transition_grade", 0, 0.8)],
  });
  const rows = [row("A", 50), shell, row("B", 34.0), row("C", 10, { holdings_weight_pct: 5 })];
  const w = why(shell, rows, { as_of: "2026-11-15", weights: { version: 2, activated_by: "A. Analyst", activated_at: "2026-11-12T09:00:00Z" } });
  assert.equal(w.first, "Shell plc — priority score 34.0 of 100, rank 2 of 4.");
  assert.equal(w.second, "Weights: priority_weights v2, activated 12 Nov 2026 by A. Analyst.");
  assert.deepEqual(w.weighted.map((l) => [l.label, l.value.text, l.points]), [["Open triggers", "1 high, 1 medium", 24], ["Escalated", "1 engagement", 10]]);
  assert.equal(w.total, "34.0");
  assert.equal(w.weighted.reduce((s, l) => s + l.points, 0).toFixed(1), w.total);
  assert.deepEqual(w.noData.map((l) => l.label), ["Next meeting"]);
  assert.deepEqual(w.notWeighted.map((l) => [l.label, l.value.text, l.value.simulated]), [["ESG score", "3.9", true], ["Transition grade", "E Not credible", true]]);
  assert.equal(LAST_LINE, "This score is one indicator. Sorting, filtering and selecting are your call.");
  assert.equal(why(shell, rows, { as_of: "2026-11-15", weights: { version: 0, activated_by: null, activated_at: null } }).second, "Weights: priority_weights v0 (bundled default).");
  assert.equal(partValue("holdings_weight", shell, rows, "2026-11-15").text, "1.204 %  (rank 2 of 4)");
});

test("ranks: ties share a rank, an empty value has none", () => {
  const rows = [row("A", 50), row("B", 40), row("C", 40), row("D", 10)];
  assert.deepEqual(rows.map((r) => rankOf(rows, (x) => x.score, r)), [1, 2, 2, 4]);
  assert.equal(rankOf(rows, () => null, rows[0]), null);
});

test("AC-95: ↓ and ↑ step through the table's order and stop at either end", () => {
  const order = [row("A", 3), row("B", 2), row("C", 1)];
  assert.equal(neighbour(order, "A", 1), "B");
  assert.equal(neighbour(order, "B", -1), "A");
  assert.equal(neighbour(order, "C", 1), null);
  assert.equal(neighbour(order, "A", -1), null);
  assert.equal(neighbour(order, "Z", 1), null);
});

test("PR 7: each commitment flag's message shows under the Value of its row", () => {
  const r = row("X", 7.5, {
    overdue_commitments: 1, broken_commitments: 1,
    commitment_flags: [
      { kind: "broken", message: 'Commitment broken: "Split chair" was marked not met on 2026-10-01.' },
      { kind: "overdue", message: 'Commitment overdue: "Publish targets" was due 2026-10-15.' },
    ],
    parts: [part("overdue_commitments", 15, 0.5), part("broken_commitments", 0, 0.5)],
  });
  const w = why(r, [r], { as_of: "2026-11-16", weights: { version: 0, activated_by: null, activated_at: null } });
  assert.deepEqual(w.weighted.map((l) => [l.value.text, l.messages]), [["1", ['Commitment overdue: "Publish targets" was due 2026-10-15.']]]);
  assert.deepEqual(w.notWeighted.map((l) => [l.label, l.value.text, l.messages]), [["Broken commitments", "1", ['Commitment broken: "Split chair" was marked not met on 2026-10-01.']]]);
});
