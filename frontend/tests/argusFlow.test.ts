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
    ["r1", "Extraction", 3, "Running", 4, "bob", "#/extraction/extract"],
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
