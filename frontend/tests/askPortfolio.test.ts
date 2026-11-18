import test from "node:test";
import assert from "node:assert/strict";
import { askBody, snapshotLine, trendRangeError, trendTable } from "../src/lib/askPortfolio.ts";

test("askBody sends the typed question and the pane's selection as fields", () => {
  assert.deepEqual(askBody("How much do we hold?", [], "2026-04-30", null), {
    question: "How much do we hold?", portfolio_ids: [], as_of: "2026-04-30",
  });
  assert.deepEqual(askBody("q", ["core_equity_europe"], undefined, null), { question: "q", portfolio_ids: ["core_equity_europe"] });
  assert.deepEqual(askBody("q", [], undefined, ["2026-04-30", "2026-10-31"]), {
    question: "q", portfolio_ids: [], date_range: ["2026-04-30", "2026-10-31"],
  });
});

test("trendRangeError", () => {
  assert.equal(trendRangeError("2026-10-31", "2026-04-30"), "The end date is before the start date.");
  assert.equal(trendRangeError("2026-04-30", "2026-10-31"), null);
  assert.equal(trendRangeError("2026-04-30", ""), null);
});

test("snapshotLine", () => {
  assert.equal(snapshotLine(["2026-04-30"]), "Snapshot used: 2026-04-30");
  assert.equal(snapshotLine(["2026-04-30", "2026-07-31"]), "Snapshots used: 2026-04-30, 2026-07-31");
  assert.equal(snapshotLine([]), null);
});

test("trendTable: a row per date, a column per group, a dash where a group is absent", () => {
  const point = (as_of: string, rows: [string, number][]) => ({
    as_of,
    result: {
      total_market_value_eur: rows.reduce((s, r) => s + r[1], 0),
      rows: rows.map(([group_value, market_value_eur]) => ({ group_value, market_value_eur, holding_count: 1 })),
    },
  });
  const trend = [point("2026-07-31", [["Autos", 3000000], ["Energy", 1000000]]), point("2026-04-30", [["Autos", 2000000]])];
  const table = trendTable(trend, "market_value_sum");
  assert.deepEqual(table.headers, ["As of", "Autos", "Energy", "Total"]);
  assert.deepEqual(table.rows.map((r) => r[0]), ["2026-04-30", "2026-07-31"]);
  assert.equal(table.rows[0][2], "—");
  assert.deepEqual(trendTable(trend, "count").headers, ["As of", "Autos", "Energy"]);
  assert.equal(trendTable(trend, "market_value_sum", "millions").rows[0][3], (2).toLocaleString(undefined, { minimumFractionDigits: 2 }));
});
