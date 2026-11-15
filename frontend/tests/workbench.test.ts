import test from "node:test";
import assert from "node:assert/strict";
import {
  COLUMNS,
  DEFAULT_SORT,
  PAGE_SIZE,
  day,
  nextMeetingText,
  nextSort,
  programmeChip,
  sortRows,
  tierText,
  totalText,
  weightsTotal,
  withProgramme,
  withSelection,
} from "../src/lib/workbench.ts";
import type { WorklistRow } from "../src/types.ts";

const col = (id: string) => COLUMNS.find((c) => c.id === id)!;

function row(i: number, over: Partial<WorklistRow> = {}): WorklistRow {
  return {
    issuer_id: `C${i}`, company: `Company ${String(i).padStart(4, "0")}`, sector: "Energy", identifier: `C${i}`,
    engaged: { yes: false, last: null }, last_topics: [], programmes: [], norms_violation: null,
    equity_held_eur_m: 1, ownership_pct: null, holdings_weight_pct: (i % 97) / 10, aum_held_eur_m: i % 13,
    coverage_tier: ["bilateral", "letter", "monitor"][i % 3], coverage_tier_confirmed: true,
    triggers: { high: i % 2, medium: i % 3, low: 0 }, open_engagements: 0, escalated: 0, overdue_commitments: 0,
    next_meeting: i % 4 ? { days: i % 365, estimated: true, last_meeting: "2026-02-24" } : null,
    transition_grade: null, esg_score: null, controversy: null, carbon_intensity: null, esg_extra: {},
    score: Math.round((i * 7919) % 1000) / 10, parts: [], selection: null, held_in: [], selected_elsewhere: [],
    notes: { count: 0, latest: null },
    ...over,
  };
}

test("AC-24, AC-64: click Score, shift-click Holdings weight, AUM held, Grade: three keys, the fourth replaces the third", () => {
  let keys = nextSort(DEFAULT_SORT, col("score"), false);
  assert.deepEqual(keys, [{ id: "score", desc: true }]); // the default's two keys give way to one, not a flip
  keys = nextSort(keys, col("holdings_weight"), true);
  assert.deepEqual(keys, [{ id: "score", desc: true }, { id: "holdings_weight", desc: true }]);
  keys = nextSort(keys, col("aum_held"), true);
  keys = nextSort(keys, col("transition_grade"), true);
  assert.deepEqual(keys.map((k) => k.id), ["score", "holdings_weight", "transition_grade"]);
  assert.equal(keys[2].desc, false); // a grade sorts A → F first
  assert.deepEqual(nextSort([{ id: "score", desc: true }], col("score"), false), [{ id: "score", desc: false }]); // clicked again: flips
  assert.deepEqual(nextSort([], col("company"), false), [{ id: "company", desc: false }]); // text ascending first
});

test("AC-42: rows with equal score are ordered by holdings weight, largest first", () => {
  const rows = [row(1, { score: 10, holdings_weight_pct: 1 }), row(2, { score: 10, holdings_weight_pct: 3 }), row(3, { score: 20, holdings_weight_pct: 0 })];
  const keys = [{ id: "score", desc: true }, { id: "holdings_weight", desc: true }];
  assert.deepEqual(sortRows(rows, keys, COLUMNS).map((r) => r.issuer_id), ["C3", "C2", "C1"]);
});

test("AC-43: an empty Next meeting sorts last in both directions", () => {
  const rows = [row(0), row(1), row(2), row(4), row(5)]; // C0 and C4 have no meeting
  for (const desc of [false, true]) {
    const ids = sortRows(rows, [{ id: "next_meeting", desc }], COLUMNS).map((r) => r.issuer_id);
    assert.deepEqual(ids.slice(-2).sort(), ["C0", "C4"], `desc=${desc}`);
  }
});

test("tiers sort Bilateral → Letter → Monitor, proposed with confirmed; triggers by high, medium, low", () => {
  const rows = [row(1, { coverage_tier: "monitor" }), row(2, { coverage_tier: "bilateral", coverage_tier_confirmed: false }), row(3, { coverage_tier: "letter" })];
  assert.deepEqual(sortRows(rows, [{ id: "coverage_tier", desc: false }], COLUMNS).map((r) => r.coverage_tier), ["bilateral", "letter", "monitor"]);
  const t = [row(1, { triggers: { high: 0, medium: 5, low: 5 } }), row(2, { triggers: { high: 1, medium: 0, low: 0 } })];
  assert.deepEqual(sortRows(t, [{ id: "triggers", desc: true }], COLUMNS).map((r) => r.issuer_id), ["C2", "C1"]);
  assert.equal(tierText(rows[1]), "Bilateral (proposed)");
  assert.equal(tierText(rows[0]), "Monitor");
});

test("Selected sorts Confirmed, Proposed, empty; text sorts any case", () => {
  const sel = (status: "proposed" | "confirmed") => ({ status, proposed_by: "a", proposed_at: "", confirmed_by: null, confirmed_at: null, weights_version: 0 });
  const rows = [row(1), row(2, { selection: sel("proposed") }), row(3, { selection: sel("confirmed") })];
  assert.deepEqual(sortRows(rows, [{ id: "selection", desc: false }], COLUMNS).map((r) => r.issuer_id), ["C3", "C2", "C1"]);
  const names = [row(1, { company: "beta" }), row(2, { company: "Alpha" }), row(3, { company: "gamma" })];
  assert.deepEqual(sortRows(names, [{ id: "company", desc: false }], COLUMNS).map((r) => r.company), ["Alpha", "beta", "gamma"]);
});

test("cell texts the spec fixes: programme chips, dates, next meeting, weights total", () => {
  assert.equal(programmeChip({ name: "Water engagement programme", status: "proposed" }), "Water ?");
  assert.equal(programmeChip({ name: "Climate Engagement Programme", status: "confirmed" }), "Climate ✓");
  assert.equal(day("2026-09-12"), "12 Sep 2026");
  assert.deepEqual(nextMeetingText({ days: 101, estimated: true, last_meeting: "2026-02-24" }, "2026-11-15"), {
    text: "≈ 101 d (est.)",
    title: "Estimated: last meeting 24 Feb 2026 + 1 year. No meeting calendar is connected.",
  });
  assert.equal(totalText(weightsTotal([{ weight: 25 }, { weight: 70 }])), "Total 95 — must be 100");
  assert.equal(totalText(100), "Total 100");
});

test("AC-27: with 2,500 rows, sorting by Score and then by Company each finish in under 200 ms", () => {
  const rows = Array.from({ length: 2500 }, (_, i) => row(i));
  for (const keys of [[{ id: "score", desc: true }], [{ id: "company", desc: false }]]) {
    const t = performance.now();
    const page = sortRows(rows, keys, COLUMNS).slice(0, PAGE_SIZE);
    const ms = performance.now() - t;
    assert.equal(page.length, PAGE_SIZE);
    assert.ok(ms < 200, `${keys[0].id}: ${ms.toFixed(1)} ms`);
  }
});

test("after an action, rows take their selection and programme chips from the response", () => {
  const rows = [row(1), row(2, { programmes: [{ programme_id: "water", name: "Water engagement programme", status: "proposed" }] })];
  const list = {
    cycle: "2026-Q4", current: true,
    rows: [{ issuer_id: "C1", company: "Company 0001", in_scope: true, status: "proposed" as const, proposed_by: "a", proposed_at: "t", confirmed_by: null, confirmed_at: null, weights_version: 0 }],
  };
  const sel = withSelection(rows, list);
  assert.equal(sel[0].selection?.status, "proposed");
  assert.equal("issuer_id" in (sel[0].selection ?? {}), false);
  assert.equal(sel[1].selection, null);
  const member = (issuer_id: string, status: "proposed" | "confirmed" | "ended") => ({
    issuer_id, company: "", status, proposed_by: "a", proposed_at: "t", confirmed_by: null, confirmed_at: null, ended_by: null, ended_at: null, end_reason: null,
  });
  const detail = { programme_id: "water", name: "Water engagement programme", built_in: false, confirmed: 1, proposed: 0, created_by: "a", created_at: "t", members: [member("C1", "confirmed"), member("C2", "ended")] };
  const progs = withProgramme(rows, detail);
  assert.deepEqual(progs[0].programmes.map(programmeChip), ["Water ✓"]);
  assert.deepEqual(progs[1].programmes, []); // an ended membership leaves the row
});
