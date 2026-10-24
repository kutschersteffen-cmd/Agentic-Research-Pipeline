import { test } from "node:test";
import assert from "node:assert/strict";
import { cents, footprintTotal, homeShare, linkText, nodeHash, percent, searchable, tile } from "../src/lib/valueChain.ts";

test("flows in cents", () => {
  assert.equal(cents(0.0738), "7.4¢"); assert.equal(cents(0.0079798, 2), "0.80¢");
  assert.equal(linkText({ direct: 0.0433, total: 0.0738 }, "total"), "7.4¢ (direct 4.3¢)");
  assert.equal(linkText({ direct: 0.0433, total: 0.0738 }, "direct"), "4.3¢");
});
test("tiles, percents, totals", () => {
  assert.equal(tile(14.3462), "14.3"); assert.equal(tile(null), "—");
  assert.equal(percent(0.8452), "85%"); assert.equal(percent(0.845), "85%"); assert.equal(percent(null), "—");
  assert.equal(footprintTotal(973.926, "t CO₂e"), "973.9 t CO₂e");
  assert.equal(homeShare(0.8452, "CN"), "85% in CN"); assert.equal(homeShare(null, "CN"), "");
});
test("search only with a non-space character; hashes encode ids", () => {
  assert.equal(searchable(" "), false); assert.equal(searchable("wa"), true);
  assert.equal(nodeHash("CN.95"), "#/valueChain/CN.95"); assert.equal(nodeHash("CN.95", "tree"), "#/valueChain/CN.95/tree");
});
