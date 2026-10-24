import { test } from "node:test";
import assert from "node:assert/strict";
import { continueLabel, documentsText, extractedBeforeText, filePath, filesLabel, flowHref, identifierList, keepPassing, removeAll } from "../src/lib/argusFlow.ts";
import { argusRows } from "../src/lib/argusStart.ts";
import type { ArgusFlow, FlowFile, FlowRow, RunManifest } from "../src/types.ts";

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

const file = (key: string, company_id: string, state: FlowFile["state"], f: Partial<FlowFile> = {}): FlowFile =>
  ({ key, company_id, doc_type: "10-K", file_name: key, source: "upload", on_disk: true, url: null, year: 2025, company_match: "name",
    duplicate_of: null, check: "✓ name, year", passed: true, state, ...f }) as FlowFile;
const fail = (key: string) => file(key, "c", null, { passed: false, check: "Year unclear" });
const dup = (key: string) => file(key, "c", null, { passed: false, duplicate_of: "a.pdf", check: "Duplicate of a.pdf, skipped" });

test("continue counts kept files and their companies", () => {
  const fs = [file("a", "apple", "kept"), file("b", "apple", "kept"), file("c", "msft", null), file("d", "sap", "removed")];
  assert.equal(filesLabel(fs), "Continue with 2 files for 1 company");
  assert.equal(filesLabel([file("a", "apple", "kept"), file("b", "msft", "kept"), file("c", "sap", "kept")]), "Continue with 3 files for 3 companies");
  assert.equal(filesLabel([file("a", "apple", "kept")]), "Continue with 1 file for 1 company");
});

test("keep all that pass leaves failing and duplicate files alone", () => {
  assert.deepEqual(keepPassing([file("a", "c", "removed"), fail("b"), dup("c")]), { a: "kept" });
});

test("remove all covers everything but duplicates", () => {
  assert.deepEqual(removeAll([file("a", "c", "kept"), fail("b"), dup("c")]), { a: "removed", b: "removed" });
});

test("only files in the app's folder have a path to open", () => {
  assert.deepEqual(filePath(file("apple/10-K/a b.pdf", "apple", "kept")), ["apple", "10-K", "a b.pdf"]);
  assert.equal(filePath(file("https://sec.gov/x.htm", "apple", "kept", { on_disk: false })), null);
});
