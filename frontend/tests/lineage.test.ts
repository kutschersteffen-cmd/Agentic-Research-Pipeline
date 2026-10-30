import test from "node:test";
import assert from "node:assert/strict";
import { lineageFromEntity, lineageLines } from "../src/lib/lineage.ts";

const A = {
  entity_id: "A", name: "Company A", status: "scored", reasons: [], score: 61.2, rank: 2, tier: 1, tier_name: "Tier 1",
  framework_id: "fw_s", framework_version: 1, snapshot_id: "pub_1", as_of: "2026-10-30", published_by: "Bob", published_at: "2026-10-30T10:00:00Z",
  criteria: [
    {
      column: "auth_scope1", contribution: 30.6, imputed: false, missing_reason: null, link: "authoritative", value_id: 17,
      value: { value: 90, unit: "tCO2e", status: "value", reason: null, period_end: "2025-12-31", framework_id: "fw_f", framework_version: 1, superseded: false, current_valid_to: null },
      inputs: [{ name: "scope1_tco2e", value: 90, status: "approved", source: "extraction", provider: null, period_end: "2025-12-31", unit: "tCO2e", observation_id: 42, published_fact_id: null, link: "observation", citations: [{ doc_id: "d1", page: 4, quote: "Scope 1: 90 tCO2e", grounded: true }] }],
    },
  ],
};

test("AC-23 chain lines for a scored row", () => {
  const l = lineageLines(A);
  assert.equal(l.criteria[0].value, "auth_scope1 = 90 tCO2e");
  assert.ok(l.criteria[0].inputs.includes("scope1_tco2e = 90 · approved · extraction · 2025-12-31"));
  assert.ok(l.criteria[0].citations.includes('d1 p.4 · "Scope 1: 90 tCO2e"'));
});

test("AC-23/AC-32 a no-score row shows its reason", () => {
  const l = lineageLines({ ...A, status: "no_score", score: null, reasons: ["required_missing: auth_scope1 (not_in_dataset)"], criteria: [] });
  assert.deepEqual(l.reasons, ["required_missing: auth_scope1 (not_in_dataset)"]);
  assert.equal(l.header, "Company A · no score");
});

test("links that stop are named, never hidden", () => {
  const l = lineageLines({ ...A, criteria: [{ column: "x", contribution: 0, imputed: false, missing_reason: null, link: "dataset_cell", value_id: null, value: null, inputs: null }, { link: "not_recorded" }] });
  assert.equal(l.criteria[0].value, "x: from the table (no authoritative value)");
  assert.equal(l.criteria[1].value, "Lineage not recorded (published before lineage)");
});

test("a live result becomes the same lineage shape", () => {
  const entity = { entity_key: "A", name: "Company A", status: "no_score", reasons: ["required_missing: auth_scope1 (not_in_dataset)"], score: null, rank: null, tier: null, tier_name: null, contributions: [{ column: "auth_scope1", contribution: 0, imputed: false, value_id: 13, missing_reason: "not_in_dataset" }] };
  const l = lineageFromEntity(entity, {});
  assert.equal(l.status, "no_score");
  assert.equal(l.criteria[0].link, "missing");
});
