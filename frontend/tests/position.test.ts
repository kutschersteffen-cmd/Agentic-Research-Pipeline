import { test } from "node:test";
import assert from "node:assert/strict";
import { checkGrid, criterion, editorDraft, latestStandards, positionState, releasedFieldIds } from "../src/lib/position.ts";

test("a version reads as approved by its approver, else as drafted by its author", () => {
  const view = { approvals: [{ version: 1, approved_by: "own", approved_at: "t" }], approved_version: 1 };
  assert.equal(positionState(view, { version: 1, created_by: "model" }), "Approved by own");
  assert.equal(positionState(view, { version: 2, created_by: "own" }), "Draft by own");
  assert.equal(positionState({ approvals: [], approved_version: null }, { version: 1, created_by: "model" }), "Draft by model");
});

test("a criterion names the field and prints the value as JSON", () => {
  assert.equal(criterion({ field_id: "f", operator: "==", value: true }, { f: "Scope 3 disclosed" }), "Scope 3 disclosed == true");
  assert.equal(criterion({ field_id: "g", operator: ">=", value: 20 }, {}), "g >= 20");
  assert.equal(criterion({ field_id: "r", operator: "==", value: "B" }, {}), 'r == "B"');
});

test("the check grid has one row per company and one column per standard", () => {
  const r = (company_id: string, name: string, standard_id: string, result: string) =>
    ({ company_id, name, standard_id, result, value: null, period_end: null });
  const grid = checkGrid({ checked_at: "t", flagged: 1, results: [
    r("C1", "Alpha", "S1", "met"), r("C1", "Alpha", "S2", "met"), r("C2", "Beta", "S1", "unmet"), r("C2", "Beta", "S2", "no_data"),
  ] });
  assert.deepEqual(grid, { standards: ["S1", "S2"], rows: [{ name: "Alpha", cells: ["Met", "Met"] }, { name: "Beta", cells: ["Unmet", "No data"] }] });
});

test("version 0 is never the latest standards version", () => {
  const v = (version: number) => ({ version, created_by: "m", created_at: null, standards: [], schema: null });
  assert.equal(latestStandards([v(0)]), null);
  assert.equal(latestStandards([v(0), v(1), v(2)])?.version, 2);
});

test("the editor turns fields released since the version was saved into existing data", () => {
  const std = (standard_id: string, field_id: string, data: "existing" | "new") =>
    ({ standard_id, title: "t", expectation: "e", definition: "d", where_reported: "w", rests_on: [1], severity: "low" as const,
       field_id, operator: "==" as const, value: true, data });
  const field = (field_id: string) => ({ field_id, name: field_id, description: "d", data_type: "boolean", extraction_instructions: "x" });
  const v1 = { version: 1, created_by: "model", created_at: null, standards: [std("S1", "old", "existing"), std("S2", "plan", "new")],
               schema: { schema_id: "theme_std_x", name: "n", fields: [field("plan")] } } as never;
  const view = { versions: [v1], active_version: 1 };
  assert.deepEqual([...releasedFieldIds(view)], ["plan"]);
  const draft = editorDraft(v1, releasedFieldIds(view));
  assert.deepEqual(draft.standards.map((s) => s.data), ["existing", "existing"]);
  assert.deepEqual(draft.new_fields, []);
  assert.deepEqual(editorDraft(v1, new Set()).new_fields?.map((f) => f.field_id), ["plan"]);
});
