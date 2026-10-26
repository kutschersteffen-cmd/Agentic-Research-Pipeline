import { test } from "node:test";
import assert from "node:assert/strict";
import { actionsLine, companyNames, factsLine, financialsLine, fixed } from "../src/lib/contextBrief.ts";
import type { ContextBrief } from "../src/types.ts";

const brief = (facts: Partial<ContextBrief["facts"]>): ContextBrief => ({
  status: "written", error: null, written_at: "", evidence: [], why_now: [], early_evidence: [], sectors: [], dropped_statements: 0,
  activities: { by_company: [], groups: [], unclassified_company_ids: [] },
  companies: [{ company_id: "acme", name: "Acme", isic_division: "27" }, { company_id: "beta", name: "Beta", isic_division: null }],
  facts: {
    first_seen: "2026-09-01", last_seen: "2026-09-20", independent_sources: 5, company_count: 4, velocity: 1.005, breadth: 0, persistence: 0,
    novelty: 1, materiality: 0, contradiction: 0, action_counts: { capex: 1, hiring: 0, orders: 1, capacity: 1, partnership: 1 }, ...facts,
  },
});

test("rounds half away from zero", () => {
  assert.deepEqual([fixed(1.005, 2), fixed(-1.005, 2), fixed(2, 2), fixed(25, 1)], ["1.01", "-1.01", "2.00", "25.0"]);
});

test("facts line and corporate actions", () => {
  assert.equal(factsLine(brief({})), "Mentions 2026-09-01 to 2026-09-20 · 5 independent sources · 4 companies · velocity 1.01");
  assert.match(factsLine(brief({ first_seen: null, last_seen: null })), /^Mention dates unknown · /);
  assert.equal(actionsLine(brief({})), "Corporate actions: capex 1, orders 1, capacity 1, partnership 1");
  assert.equal(actionsLine(brief({ action_counts: { capex: 2, hiring: 0, orders: 0, capacity: 0, partnership: 0 } })), "Corporate actions: capex 2");
});

test("financials and company names", () => {
  const item = { evidence_id: "E7", kind: "financials" as const, company_id: "acme", capex_pct_change: 0.25, rnd_pct_change: null };
  assert.equal(financialsLine(item, "Acme"), "Acme: CapEx +25.0%, R&D n/a (SEC filings)");
  assert.equal(financialsLine({ ...item, capex_pct_change: -0.0325 }, "Acme"), "Acme: CapEx -3.3%, R&D n/a (SEC filings)");
  // Same cases as the backend's _pct, so the model and the card read one figure.
  assert.deepEqual(
    [0.0125, -0.0325, -0.0001, 0].map((x) => financialsLine({ ...item, capex_pct_change: x }, "A").split(",")[0]),
    ["A: CapEx +1.3%", "A: CapEx -3.3%", "A: CapEx 0.0%", "A: CapEx +0.0%"],
  );
  assert.equal(companyNames(brief({}), ["beta", "acme"]), "Beta, Acme");
});
