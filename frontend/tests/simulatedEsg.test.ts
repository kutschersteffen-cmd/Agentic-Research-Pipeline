import test from "node:test";
import assert from "node:assert/strict";
import { simulatedEsgView } from "../src/pages/company/simulatedEsg.ts";
import type { SimulatedObservation } from "../src/types.ts";

const o = (field_id: string, field_name: string, value: SimulatedObservation["value"], unit: string | null = null): SimulatedObservation => ({
  company_id: "isin_DE0007164600", field_id, field_name, value, unit, period: "2026-11", observed_at: "2026-11-02T00:00:00+00:00",
  source: "simulated", conflicting_sources: false, conflicting_value: null, conflicting_source_label: null, notes: "",
});

test("simulatedEsgView: grade as letter and label, peer group, climate values and the controversial shares only", () => {
  const view = simulatedEsgView([
    o("climate_scope1_tco2e", "Scope 1 GHG emissions", 12345.678, "tCO2e"),
    o("climate_green_revenue_pct", "Green revenue share", 12.5, "%"),
    o("esg_score", "ESG score", 6.1, "0 to 10"),
    o("oil_revenue_pct", "Oil revenue share", 0.6183, "fraction of revenue"),
    o("green_revenue_pct", "Green revenue share", 0.125, "fraction of revenue"),
    o("transition_grade", "Transition grade", "B"),
    o("transition_grade_label", "Transition grade label", "Credible"),
    o("peer_group", "Peer group", "Information Technology"),
  ]);
  assert.deepEqual(view, {
    grade: "B Credible",
    peerGroup: "Information Technology",
    rows: [
      { fieldId: "climate_scope1_tco2e", label: "Scope 1 GHG emissions", value: "12,345.68 tCO2e" },
      { fieldId: "climate_green_revenue_pct", label: "Green revenue share", value: "12.5%" },
      { fieldId: "oil_revenue_pct", label: "Oil revenue share", value: "61.83%" },
    ],
  });
});

test("simulatedEsgView: nothing to show without observations", () => {
  assert.equal(simulatedEsgView([]), null);
  assert.deepEqual(simulatedEsgView([o("climate_scope1_tco2e", "Scope 1", 1, "tCO2e")])?.grade, null);
});
