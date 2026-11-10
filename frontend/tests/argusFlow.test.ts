import { test } from "node:test";
import assert from "node:assert/strict";
import { continueLabel, documentsText, extractedBeforeText, flowHref, identifierList } from "../src/lib/argusFlow.ts";
import { argusRows } from "../src/lib/argusStart.ts";
import type { ArgusFlow, FlowRow, RunManifest } from "../src/types.ts";

const flow = (f: Partial<ArgusFlow>): ArgusFlow =>
  ({ flow_id: "f", created_at: "2026-10-05", updated_at: "2026-10-05", started_by: "alice", started_by_name: "Alice", step: 1, companies: [],
    identity_run_id: null, rows: [], ...f }) as ArgusFlow;
const row = (r: Partial<FlowRow>): FlowRow =>
  ({ company_id: "c", central_id: null, name: "C", identifiers: {}, master_identifiers: {}, sector: null, country: null, problem: null,
    extracted_before: null, documents: 0, document_types: [], ...r }) as FlowRow;

test("extracted before and documents read as the spec writes them", () => {
  assert.equal(extractedBeforeText({ label: "S v2", date: "2026-10-01", approved: 3, waiting: 1 }), "S v2 · 2026-10-01 · 3 approved · 1 waiting");
  assert.equal(extractedBeforeText(null), "Never");
  assert.equal(documentsText(2, ["annual", "sustainability"]), "2 (annual, sustainability)");
  assert.equal(documentsText(0, []), "None");
});

test("continue label and flow href", () => {
  assert.deepEqual([continueLabel(1), continueLabel(4)], ["Continue with 1 company", "Continue with 4 companies"]);
  assert.equal(flowHref("f1", 3), "#/argus/f1/3");
});

test("identifiers: the company's own first, then master ones not already shown", () => {
  const r = row({ identifiers: { LEI: ["L1"], USER: ["AAPL-X"] }, master_identifiers: { LEI: ["L1"], ISIN: ["US1"] } });
  assert.deepEqual(identifierList(r), ["LEI L1", "USER AAPL-X", "ISIN US1"]);
});

test("a draft lists as Draft at its step, newest first, opening the flow", () => {
  const run = { run_id: "r1", run_type: "extraction", status: "running", created_at: "2026-10-01", updated_at: "2026-10-01", params: { started_by: "bob" },
    company_count: 3, completed_count: 0, failed_count: 0, review_count: 0, input_tokens: 0, output_tokens: 0, estimated_cost_usd: 0 } as unknown as RunManifest;
  const rows = argusRows([run], [], [flow({ flow_id: "f1", companies: [{ company_id: "a" }, { company_id: "b" }] as ArgusFlow["companies"] })]);
  assert.deepEqual(rows.map((r) => [r.runId, r.label, r.companies, r.status, r.step, r.starterName, r.openHref]), [
    ["f1", "New extraction", 2, "Draft", 1, "Alice", "#/argus/f1/1"],
    ["r1", "Extraction", 3, "Running", 4, "bob", "#/history/r1"],
  ]);
});

test("step 2 continue counts kept files and their companies", async () => {
  const { continueFilesLabel, previousYear } = await import("../src/lib/argusFlow.ts");
  const f = (company_id: string, state: "kept" | "removed" | null) => ({ company_id, state }) as never;
  assert.deepEqual(continueFilesLabel([f("a", "kept"), f("a", "kept"), f("b", "kept"), f("c", "kept"), f("c", "kept"), f("c", "kept"), f("c", "kept"), f("d", "removed"), f("e", null)]),
    { text: "Continue with 7 files for 3 companies", disabled: false });
  assert.deepEqual(continueFilesLabel([f("a", "kept")]), { text: "Continue with 1 file for 1 company", disabled: false });
  assert.deepEqual(continueFilesLabel([f("a", "removed")]), { text: "Continue with 0 files for 0 companies", disabled: true });
  assert.equal(previousYear(new Date("2026-11-09")), 2025);
});

test("step 3 start label, new documents line and repeat gate", async () => {
  const { startLabel, newDocsLine, canStart } = await import("../src/lib/argusFlow.ts");
  assert.equal(startLabel("Green capex", 2, true, 3), "Extract Green capex v2 for 3 companies");
  assert.equal(startLabel("Green capex", 2, true, 1), "Extract Green capex v2 for 1 company");
  assert.equal(startLabel("Green capex", 3, false, 3), "Try Green capex on 1 company");  // AC-29
  assert.equal(startLabel("Financials", null, true, 2), "Extract Financials for 2 companies");
  assert.equal(startLabel(null, 1, false, 2), "Loading schema…");  // not "Try  on 1 company" before the schema arrives
  assert.deepEqual([newDocsLine(1), newDocsLine(3), newDocsLine(0)],
    ["1 new document since the last run", "3 new documents since the last run", null]);
  const same = { company_id: "a", kind: "same" } as never, added = { company_id: "b", kind: "added" } as never;
  assert.equal(canStart([same, added], {}), false);  // AC-32
  assert.equal(canStart([same, added], { a: "skip" }), true);
  assert.equal(canStart([added], {}), true);
});

test("the picker lists only each schema's newest version", async () => {
  const { newestVersions } = await import("../src/lib/argusFlow.ts");
  const s = (schema_id: string, version: number, name = schema_id) => ({ schema_id, version, name, release_flag: false });
  assert.deepEqual(newestVersions([s("a", 1), s("b", 1, "B"), s("a", 3), s("a", 2)]).map((x) => [x.schema_id, x.version]), [["a", 3], ["b", 1]]);
});

import { onlyNeedsYou, progressHeader, resultRows } from "../src/lib/argusFlow.ts";
import type { ExtractedField, ExtractionRecord, ReviewItem } from "../src/types.ts";

test("progress header", () => {
  const p = { started_at: "2026-11-10T14:02:00", done: 3, total: 10, minutes_left: 8, cost_usd: 1.2, status: "running" };
  assert.equal(progressHeader(p), "Started 14:02 · 3 of 10 done · about 8 minutes left · $1.20 so far"); // AC-39
  assert.equal(progressHeader({ ...p, done: 0, minutes_left: null }), "Started 14:02 · 0 of 10 done · estimating time left · $1.20 so far");
  assert.equal(progressHeader({ ...p, minutes_left: 1 }), "Started 14:02 · 3 of 10 done · about 1 minute left · $1.20 so far");
  assert.equal(progressHeader({ ...p, status: "cancelled" }), "Started 14:02 · 3 of 10 done · $1.20 so far"); // over: no time left to estimate
});

const field = (id: string, f: Partial<ExtractedField> = {}): ExtractedField =>
  ({ field_id: id, field_name: id.toUpperCase(), value: 1, citations: [], confidence: 0.9, grounded: true, conflicting_sources: false,
     value_state: "found", period_end: "2025-12-31", ...f });
const record = (cid: string, fields: ExtractedField[]): ExtractionRecord =>
  ({ company_id: cid, issuer_key: `k${cid}`, name: cid.toUpperCase(), schema_id: "s", run_id: "r", fields, overall_confidence: 0.9, needs_review: false } as ExtractionRecord);
const item = (key: string): ReviewItem =>
  ({ item_key: key, kind: "value", run_id: "r", run_type: "extraction", payload: {}, state: "pending", escalated: false, high_risk: false, decision: null });

test("results: one row per value, what needs you first, and the filter", () => {
  const results = [
    record("a", [field("f1"), field("f2"), field("f3", { value: null, value_state: "not_found" })]),
    record("b", [field("f1"), field("f2"), field("f3"), field("f4")]),
  ];
  const rows = resultRows(results, [item("ka:f3:2025-12-31"), item("kb:f2:2025-12-31")]);
  assert.equal(rows.length, 7); // AC-40
  assert.deepEqual(rows.slice(0, 2).map((r) => r.key), ["ka:f3:2025-12-31", "kb:f2:2025-12-31"]);
  assert.ok(rows[0].notFound && !rows[1].notFound); // AC-42
  assert.equal(onlyNeedsYou(rows).length, 2); // AC-41
  assert.equal(rows[2].company, "A");
});

test("results: a company a pre-step stopped for review gets its own row", () => {
  const stop = { ...item("d"), kind: "other" as const, payload: { company_id: "d", name: "Dco", failed_step_label: "Parse & index", error: "no document text could be parsed" } };
  const rows = resultRows([record("a", [field("f1")])], [stop]);
  assert.equal(rows.length, 2);
  assert.deepEqual([rows[0].key, rows[0].company, rows[0].field, rows[0].value, rows[0].companyLevel], ["d", "Dco", "Parse & index", "no document text could be parsed", true]);
  assert.equal(onlyNeedsYou(rows).length, 1);
});
