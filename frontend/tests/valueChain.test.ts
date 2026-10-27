import { test } from "node:test";
import assert from "node:assert/strict";
import { cents, EU27, footprintTotal, homeShare, linkText, nodeHash, percent, pricePct, searchable, signed, tile } from "../src/lib/valueChain.ts";

test("flows in cents", () => {
  assert.equal(cents(0.0738), "7.4¢"); assert.equal(cents(0.0079798, 2), "0.80¢");
  assert.equal(linkText({ direct: 0.0433, total: 0.0738 }, "total"), "7.4¢ (direct 4.3¢)");
  assert.equal(linkText({ direct: 0.0433, total: 0.0738 }, "direct"), "4.3¢");
});
test("tiles, percents, totals", () => {
  assert.equal(tile(14.3462), "14.3"); assert.equal(tile(null), "—");
  assert.equal(percent(0.8452), "85%"); assert.equal(percent(0.845), "85%"); assert.equal(percent(0.285), "29%"); assert.equal(percent(null), "—");
  assert.equal(footprintTotal(973.926, "t CO₂e"), "973.9 t CO₂e");
  assert.equal(homeShare(0.8452, "CN"), "85% in CN"); assert.equal(homeShare(null, "CN"), "");
});
test("search only with a non-space character; hashes encode ids", () => {
  assert.equal(searchable(" "), false); assert.equal(searchable("wa"), true);
  assert.equal(nodeHash("CN.95"), "#/valueChain/CN.95"); assert.equal(nodeHash("CN.95", "tree"), "#/valueChain/CN.95/tree");
  assert.equal(nodeHash("a/b c", "footprint"), "#/valueChain/a%2Fb%20c/footprint");
});
test("shock numbers: signed M EUR, two-decimal price percents, EU-27 preset", () => {
  assert.equal(signed(-30.1819), "−30.2"); assert.equal(signed(12.34), "+12.3"); assert.equal(signed(-0.04), "0.0");
  assert.equal(pricePct(0.0564), "0.06%"); assert.equal(pricePct(0), "0.00%"); assert.equal(pricePct(-0.125), "−0.13%");
  assert.equal(EU27.length, 27); assert.ok(!EU27.includes("GB"));
  assert.equal(nodeHash("CN.95", "shock"), "#/valueChain/CN.95/shock");
});
