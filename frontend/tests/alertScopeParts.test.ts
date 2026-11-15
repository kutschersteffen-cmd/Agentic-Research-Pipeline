import test from "node:test";
import assert from "node:assert/strict";
import { alertScope, alertScopeParts } from "../src/lib/monitoringLabels.ts";

const PORTFOLIOS = [{ portfolio_id: "core_equity_europe", name: "Core Equity Europe" }];
const RULE = {
  rule_id: "rule_c", name: "Any weight", rule_type: "concentration_threshold", field_id: null, comparator: "gt",
  threshold_value: 0.05, company_ids: [], portfolio_ids: ["core_equity_europe"],
};
const alert = (over: object = {}) => ({
  rule_id: "rule_c", category: "threshold_breach", scope_id: "bmw", company_id: "bmw", company_name: "BMW AG",
  breach_type: "holdings_caused", ...over,
});

test("a named concentration alert: name, id, then the portfolios it covers", () => {  // AC-13, AC-14, AC-15
  assert.deepEqual(alertScopeParts(alert(), [RULE], PORTFOLIOS), { name: "BMW AG", id: "bmw", suffix: " · across Core Equity Europe" });
  assert.deepEqual(alertScopeParts(alert(), [{ ...RULE, portfolio_ids: [] }], PORTFOLIOS), { name: "BMW AG", id: "bmw", suffix: " · across all portfolios" });
  assert.deepEqual(alertScopeParts(alert(), [], PORTFOLIOS), { name: "BMW AG", id: "bmw", suffix: "" });
  assert.equal(alertScope(alert(), [RULE], PORTFOLIOS), "BMW AG bmw · across Core Equity Europe");
});

test("without a company name the scope reads as before", () => {  // AC-16
  assert.deepEqual(alertScopeParts(alert({ company_name: null }), [RULE], PORTFOLIOS), { name: null, id: null, suffix: "bmw · across Core Equity Europe" });
});

test("field-threshold and news alerts: name and id, no suffix", () => {  // AC-17, AC-18
  assert.deepEqual(alertScopeParts(alert({ rule_id: "rule_f", breach_type: "data_caused" }), [RULE], PORTFOLIOS), { name: "BMW AG", id: "bmw", suffix: "" });
  assert.deepEqual(alertScopeParts(alert({ rule_id: null, category: "news_controversy", breach_type: "unknown" }), [RULE], PORTFOLIOS), { name: "BMW AG", id: "bmw", suffix: "" });
});

test("a portfolio-aggregate alert shows the portfolio name", () => {  // AC-19
  const aggregate = alert({ rule_id: "rule_a", scope_id: "portfolio__core_equity_europe", company_id: null, company_name: null, breach_type: "unknown" });
  assert.deepEqual(alertScopeParts(aggregate, [RULE], PORTFOLIOS), { name: null, id: null, suffix: "Core Equity Europe" });
});
