import test from "node:test";
import assert from "node:assert/strict";
import { dimensionLabel, eurText, valueHeader } from "../src/lib/askPortfolio.ts";

test("dimensionLabel names every grouping", () => {  // AC-48
  const expected: Record<string, string> = {
    portfolio_id: "Portfolio", asset_class: "Asset class", company_id: "Company", company_name: "Company",
    sector: "Sector", country: "Country", currency: "Currency", gics_sector: "GICS sector",
    gics_industry_group: "GICS industry group", gics_industry: "GICS industry", gics_sub_industry: "GICS sub-industry",
    my_dim: "My dim",
  };
  for (const [id, label] of Object.entries(expected)) assert.equal(dimensionLabel(id), label);
});

test("valueHeader carries the scale and the unit", () => {
  assert.equal(valueHeader("market_value_sum"), "Market value (EUR)");
  assert.equal(valueHeader("market_value_sum", "millions", "EUR"), "Market value (EUR million)");
  assert.equal(valueHeader("weighted_avg_datapoint", "units", "tCO2e / EUR M revenue"), "Weighted avg (tCO2e / EUR M revenue)");
  assert.equal(valueHeader("weighted_avg_datapoint"), "Weighted avg");
});

test("eurText: plain EUR as before, two decimals in millions", () => {
  assert.equal(eurText(1234567), `EUR ${(1234567).toLocaleString(undefined, { maximumFractionDigits: 0 })}`);
  assert.match(eurText(1234567, "millions"), /^EUR 1[.,]23 million$/);
});
