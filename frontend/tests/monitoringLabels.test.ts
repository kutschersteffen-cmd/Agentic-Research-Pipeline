import test from "node:test";
import assert from "node:assert/strict";
import {
  alertNumber, alertRuleName, alertScope, breachTypeLabel, comparatorSymbol, fractionToPercent, percentText, percentToFraction,
  ruleCondition, ruleScope, ruleTypeLabel,
} from "../src/lib/monitoringLabels.ts";

const PORTFOLIOS = [{ portfolio_id: "core_equity_europe", name: "Core Equity Europe" }, { portfolio_id: "sustainable_leaders", name: "Sustainable Leaders Fund" }];
const FIELDS = [{ field_id: "climate_carbon_intensity", name: "Carbon intensity", unit: "tCO2e / EUR M revenue" }];
const rule = (over: object = {}) => ({
  rule_id: "rule_a", name: "Carbon cap", rule_type: "portfolio_aggregate_threshold", field_id: "climate_carbon_intensity",
  comparator: "gt", threshold_value: 50, company_ids: [], portfolio_ids: ["core_equity_europe"], ...over,
});
const CONCENTRATION = rule({ rule_id: "rule_c", name: "Any weight", rule_type: "concentration_threshold", field_id: null, threshold_value: 0.05 });
const alert = (over: object = {}) => ({
  rule_id: "rule_c", category: "threshold_breach", scope_id: "bmw", company_id: "bmw", breach_type: "holdings_caused", ...over,
});

test("percentText: at most two decimals, trailing zeros dropped", () => {  // AC-78
  assert.deepEqual([0.05, 0.0712, 0.125, 0.07, 1, 0].map(percentText), ["5%", "7.12%", "12.5%", "7%", "100%", "0%"]);
});

test("the rule form's percent round-trips to a fraction", () => {
  assert.equal(percentToFraction(5), 0.05);
  assert.equal(percentToFraction(10), 0.1);
  assert.equal(fractionToPercent(0.07), 7);
  assert.equal(fractionToPercent(0), 0);
});

test("breachTypeLabel", () => {  // AC-79
  assert.equal(breachTypeLabel("unknown", "news_controversy"), "—");
  assert.equal(breachTypeLabel("unknown", "threshold_breach"), "No earlier breach to compare");
  assert.deepEqual(["holdings_caused", "data_caused", "mixed"].map((t) => breachTypeLabel(t, "threshold_breach")), ["Holdings-caused", "Data-caused", "Mixed"]);
});

test("a rule row names its type, condition and scope", () => {
  assert.equal(ruleTypeLabel("portfolio_aggregate_threshold"), "Portfolio aggregate (WACI-style)");
  assert.equal(ruleTypeLabel("concentration_threshold"), "Single-name concentration");
  assert.equal(ruleTypeLabel("field_threshold"), "Company field threshold");
  assert.deepEqual(["gt", "gte", "lt", "lte"].map(comparatorSymbol), [">", "≥", "<", "≤"]);
  assert.equal(ruleCondition(rule(), FIELDS), "Carbon intensity > 50 tCO2e / EUR M revenue");
  assert.equal(ruleCondition(rule({ field_id: "my_field", comparator: "lte", threshold_value: 0 }), FIELDS), "my_field ≤ 0");
  assert.equal(ruleCondition(CONCENTRATION, FIELDS), "Weight of one company > 5%");
  assert.equal(ruleScope(rule(), PORTFOLIOS), "Core Equity Europe");
  assert.equal(ruleScope(rule({ portfolio_ids: ["core_equity_europe", "x"] }), PORTFOLIOS), "Core Equity Europe, x");
  assert.equal(ruleScope(rule({ portfolio_ids: [] }), PORTFOLIOS), "All portfolios");
  assert.equal(ruleScope(rule({ portfolio_ids: [], company_ids: ["bmw", "sap"] }), PORTFOLIOS), "bmw, sap");
});

test("an alert row names its rule and scope", () => {
  const rules = [rule(), CONCENTRATION];
  assert.equal(alertRuleName(alert(), rules), "Any weight");
  assert.equal(alertRuleName(alert({ rule_id: "gone" }), rules), "Deleted rule");
  assert.equal(alertRuleName(alert({ rule_id: null }), rules), "—");
  assert.equal(alertScope(alert(), rules, PORTFOLIOS), "bmw · across Core Equity Europe");
  assert.equal(alertScope(alert(), [{ ...CONCENTRATION, portfolio_ids: [] }], PORTFOLIOS), "bmw · across all portfolios");
  assert.equal(alertScope(alert({ rule_id: "gone" }), rules, PORTFOLIOS), "bmw");
  const aggregate = alert({ rule_id: "rule_a", scope_id: "portfolio__core_equity_europe", company_id: null, breach_type: "unknown" });
  assert.equal(alertScope(aggregate, rules, PORTFOLIOS), "Core Equity Europe");
  assert.equal(alertScope({ ...aggregate, scope_id: "portfolio__nope" }, rules, PORTFOLIOS), "nope");
  assert.equal(alertScope(alert({ breach_type: "data_caused" }), rules, PORTFOLIOS), "bmw");
});

test("alertNumber: percent on a concentration alert, the stored number otherwise", () => {
  assert.equal(alertNumber(alert(), 0.0712), "7.12%");
  assert.equal(alertNumber(alert(), 0), "0%");
  assert.equal(alertNumber(alert({ company_id: null, breach_type: "unknown" }), 0), "0");
  assert.equal(alertNumber(alert(), null), "--");
});
