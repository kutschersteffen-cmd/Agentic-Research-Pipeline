import test from "node:test";
import assert from "node:assert/strict";
import { count, pairOf, pairText, pairTitle, shortName, tintStep, weight } from "../src/lib/overlap.ts";

const dax = { portfolio_id: "dax", name: "DAX (public ETF holdings, 2026-11-02)", companies: 40 };
const world = { portfolio_id: "world", name: "MSCI World (public ETF holdings, 2026-11-02)", companies: 1412 };
const pair = { a: "dax", b: "world", shared_companies: 33, shared_weight_pct: 71.42 };

test("a pair cell reads shared companies · shared weight with 1 decimal, the same from either side", () => {
  assert.equal(pairText(pair), "33 · 71.4 %");
  assert.equal(pairOf([pair], "world", "dax"), pair);
  assert.equal(pairText({ ...pair, shared_companies: 1412, shared_weight_pct: 0 }), "1,412 · 0.0 %");
});

test("the pair tooltip names both funds and their company counts", () => {
  assert.equal(
    pairTitle(dax, world, pair),
    "DAX (public ETF holdings, 2026-11-02) and MSCI World (public ETF holdings, 2026-11-02) share 33 companies; DAX (public ETF holdings, 2026-11-02) holds 40, MSCI World (public ETF holdings, 2026-11-02) holds 1,412.",
  );
});

test("tint steps: 0 % none, then one step per 20 %", () => {
  assert.deepEqual([0, 0.01, 19.99, 20, 39.9, 40, 59.9, 60, 79.9, 80, 100].map(tintStep), [0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5]);
});

test("names, counts and grid weights", () => {
  assert.equal(shortName(dax.name), "DAX");
  assert.equal(shortName("Plain fund"), "Plain fund");
  assert.equal(shortName("MSCI World (EUR) Hedged (public ETF holdings, 2026-11-02)"), "MSCI World (EUR) Hedged");
  assert.equal(count(2581), "2,581");
  assert.equal(weight(4.213), "4.21");
  assert.equal(weight(null), "—");
});
