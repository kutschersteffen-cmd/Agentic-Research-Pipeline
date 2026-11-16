import test from "node:test";
import assert from "node:assert/strict";
import { COLUMNS, PAGE_SIZE, extraColumns, sortRows } from "../src/lib/workbench.ts";
import { bounds, categoryOptions, chipText, filterRows, indicators, lowOnTop, newFilter, type Filter } from "../src/lib/workbenchFilters.ts";
import type { WorklistRow } from "../src/types.ts";

function row(i: number, over: Partial<WorklistRow> = {}): WorklistRow {
  return {
    issuer_id: `C${i}`, company: `Company ${String(i).padStart(4, "0")}`, sector: i % 2 ? "Energy" : "Utilities", identifier: `C${i}`,
    engaged: { yes: false, last: null }, last_topics: [], programmes: [], norms_violation: { value: i % 3 === 0, simulated: true },
    equity_held_eur_m: 1, ownership_pct: i % 5 ? { value: (i % 50) / 1000, simulated: true } : null, holdings_weight_pct: (i % 97) / 10,
    aum_held_eur_m: i % 13, coverage_tier: ["bilateral", "letter", "monitor"][i % 3], coverage_tier_confirmed: true,
    triggers: { high: i % 2, medium: i % 3, low: 0 }, open_engagements: 0, escalated: 0, overdue_commitments: 0,
    next_meeting: null, transition_grade: null, esg_score: null, controversy: null, carbon_intensity: null, esg_extra: {},
    score: Math.round((i * 7919) % 1000) / 10, parts: [], selection: null, held_in: [], selected_elsewhere: [],
    notes: { count: 0, latest: null },
    ...over,
  };
}

const schema = [
  { field_id: "esg_score", name: "ESG score", data_type: "number" },
  { field_id: "severe_controversy", name: "Severe controversy", data_type: "boolean" },
  { field_id: "lct_category", name: "Low-carbon transition category", data_type: "enum", allowed_values: ["solutions", "neutral"] },
];
const rows = Array.from({ length: 40 }, (_, i) => row(i));
const all = indicators(COLUMNS, schema, rows);
const ind = (id: string) => all.find((i) => i.id === id)!;
const withF = (id: string, over: Partial<Filter> = {}): Filter => ({ ...newFilter(ind(id)), ...over });

test("AC-127: Add filter lists every table column and the simulated_esg fields with no column, the latter Simulated", () => {
  const ids = new Set(all.map((i) => i.id));
  for (const c of COLUMNS.filter((c) => c.id !== "triggers")) assert.ok(ids.has(c.id), c.id);
  assert.ok(ids.has("triggers_any") && ids.has("triggers_high"));
  assert.ok(!ids.has("esg:esg_score")); // a column already
  assert.deepEqual(all.filter((i) => i.simulated).map((i) => i.label), ["Low-carbon transition category", "Severe controversy"]);
  assert.equal(ind("esg:severe_controversy").kind, "yesno");
  // An esg_extra column the rows carry is listed once, with the schema's name.
  const extra = [row(1, { esg_extra: { severe_controversy: { value: true, simulated: true } } })];
  const list = indicators([...COLUMNS, ...extraColumns(extra, {})], schema, extra);
  assert.equal(list.filter((i) => i.id === "esg:severe_controversy").length, 1);
});

test("AC-128, AC-131: Ownership share spans the scope; moving the lower handle filters ≥ v and reads with 4 decimals", () => {
  assert.deepEqual(bounds(ind("ownership"), rows), { min: 0.001, max: 0.039 });
  assert.equal(filterRows(rows, [withF("ownership")]).length, rows.length); // the full range filters nothing
  const f = withF("ownership", { lo: 0.02 });
  const out = filterRows(rows, [f]);
  assert.ok(out.length > 0 && out.every((r) => (r.ownership_pct?.value as number) >= 0.02));
  assert.equal(chipText(f, rows), "Ownership share ≥ 0.0200 %");
});

test("AC-129: Norm violation opens with Yes ticked and only Yes rows remain", () => {
  const out = filterRows(rows, [withF("norms_violation")]);
  assert.ok(out.length > 0 && out.every((r) => r.norms_violation?.value === true));
  assert.equal(chipText(withF("norms_violation"), rows), "Norm violation: Yes");
});

test("AC-130: Sector offers the sectors in scope, nothing ticked, and filters nothing", () => {
  assert.deepEqual(categoryOptions(ind("sector"), rows), ["Energy", "Utilities"]);
  assert.equal(filterRows(rows, [withF("sector")]).length, rows.length);
  assert.equal(chipText(withF("sector", { values: ["Energy"] }), rows), "Sector: Energy");
});

test("AC-116, AC-138: Transition grade E with no grades shows 0 rows; Include empty shows them all", () => {
  const w = rows.slice(0, 12);
  assert.ok(categoryOptions(ind("transition_grade"), w).includes("E")); // offered though no row has a grade
  assert.equal(filterRows(w, [withF("transition_grade", { values: ["E"] })]).length, 0);
  assert.equal(filterRows(w, [withF("transition_grade", { values: ["E"], includeEmpty: true })]).length, 12);
});

test("AC-25, AC-136: grade E or F AND at least one high trigger; the count is over every row, not one page", () => {
  const many = Array.from({ length: 600 }, (_, i) =>
    row(i, { transition_grade: i % 4 ? { value: "BCEF"[i % 4], label: "", simulated: true } : null }),
  );
  const out = filterRows(many, [withF("transition_grade", { values: ["E", "F"] }), withF("triggers_high")]);
  assert.ok(out.every((r) => ["E", "F"].includes(String(r.transition_grade?.value)) && r.triggers.high >= 1));
  assert.equal(out.length, many.filter((r) => ["E", "F"].includes(String(r.transition_grade?.value)) && r.triggers.high >= 1).length);
  assert.ok(out.length > PAGE_SIZE);
});

test("AC-47: Name contains, any case", () => {
  const out = filterRows(rows, [withF("company", { text: "company 001" })]);
  assert.deepEqual(out.map((r) => r.issuer_id), ["C10", "C11", "C12", "C13", "C14", "C15", "C16", "C17", "C18", "C19"]);
});

test("AC-132: removing one chip leaves the others", () => {
  const both = [withF("ownership", { lo: 0.02 }), withF("norms_violation")];
  const left = both.filter((f) => f.ind.id !== "norms_violation");
  assert.equal(left.length, 1);
  assert.ok(filterRows(rows, left).length > filterRows(rows, both).length);
});

test("AC-134: in a narrower scope the bounds follow its rows, a handle outside them is clamped, the text updates", () => {
  const fund = rows.filter((r) => (r.ownership_pct?.value as number) >= 0.03);
  const f = withF("ownership", { lo: 0.02, hi: 0.035 });
  assert.equal(chipText(f, rows), "Ownership share 0.0200 – 0.0350 %");
  assert.deepEqual(bounds(ind("ownership"), fund), { min: 0.031, max: 0.039 });
  assert.equal(chipText(f, fund), "Ownership share ≤ 0.0350 %"); // the lower end is clamped to the fund's minimum
  assert.ok(filterRows(fund, [f]).every((r) => (r.ownership_pct?.value as number) <= 0.035));
});

test("AC-139: with 2,500 rows, a Holdings weight range filter and the sort redraw in under 200 ms per move", () => {
  const big = Array.from({ length: 2500 }, (_, i) => row(i));
  for (const lo of [0.5, 1, 2.5, 5]) {
    const t = performance.now();
    const page = sortRows(filterRows(big, [withF("holdings_weight", { lo })]), [{ id: "score", desc: true }], COLUMNS).slice(0, PAGE_SIZE);
    const ms = performance.now() - t;
    assert.ok(page.length > 0 && page.every((r) => (r.holdings_weight_pct ?? 0) >= lo));
    assert.ok(ms < 200, `lo=${lo}: ${ms.toFixed(1)} ms`);
  }
});

test("AC-128: a Lowest handle pushed to the top end lies above Highest, so it can be dragged back", () => {
  const b = { min: 0, max: 10 };
  assert.equal(lowOnTop(10, b), true);
  assert.equal(lowOnTop(2, b), false); // at the bottom end Highest stays on top and can be dragged up
});
