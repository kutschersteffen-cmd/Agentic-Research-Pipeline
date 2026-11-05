import { test } from "node:test";
import assert from "node:assert/strict";
import { activityLine, cents, EU27, exposureHash, footprintTotal, homeShare, inRegion, lensLine, linkText, naceLinkLine, nodeLine, meur, nodeHash, nodeQuery, pct1, percent, pickerHits, portfolioHash, pricePct, recipesHash, routeText, searchable, shockHash, signed, tile, tonnes, unresolvedText, partToRow, rowToPart } from "../src/lib/valueChain.ts";

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
test("tonnes extracted: one decimal below 1,000 t, whole with separators from 1,000 t (rounded first)", () => {
  assert.equal(tonnes(143.3869), "143.4 t"); assert.equal(tonnes(0), "0.0 t");
  assert.equal(tonnes(999.94), "999.9 t"); assert.equal(tonnes(999.96), "1,000 t"); assert.equal(tonnes(1283.0655), "1,283 t");
});
test("portfolio view: one-decimal percents, unresolved parts, the activity line, hashes", () => {
  assert.equal(pct1(0.55), "55.0%"); assert.equal(pct1(0.9), "90.0%"); assert.equal(pct1(0.10714), "10.7%"); assert.equal(pct1(0.00285), "0.3%");
  assert.equal(unresolvedText({ sectors: ["A", "B"], share: 0.4 }), "Not in this edition: A, B 40.0%");
  assert.equal(unresolvedText({ region: "WA", sector: "Mining of copper ores and concentrates", share: 1 }), "Not in this edition: WA · Mining of copper ores and concentrates 100.0%");
  assert.equal(activityLine({ name: "Copper and nickel mining", direct_weight: 0.35, upstream_share: 0.5193 }), "Copper and nickel mining: 35.0% of NAV directly · 51.9% of upstream");
  assert.equal(portfolioHash(), "#/valueChain/portfolio"); assert.equal(portfolioHash("P 1"), "#/valueChain/portfolio/P%201");
});
test("revenue exposure formats and hashes", () => {
  assert.equal(meur(24.7261), "24.7 M EUR");
  assert.equal(exposureHash("DE.3"), "#/valueChain/DE.3/exposure"); assert.equal(exposureHash("DE.3", "CN.3"), "#/valueChain/DE.3/exposure/CN.3");
  assert.equal(exposureHash("recipe:ab12"), "#/valueChain/recipes/ab12/exposure"); assert.equal(exposureHash("recipe:ab12", "DE.2"), "#/valueChain/recipes/ab12/exposure/DE.2");
  assert.equal(recipesHash(), "#/valueChain/recipes"); assert.equal(recipesHash("new"), "#/valueChain/recipes/new");
  assert.equal(routeText(["CN.3", "DE.3"], { "CN.3": "Other business activities · CN", "DE.3": "Other business activities · DE" }), "Other business activities · CN → Other business activities · DE");
  assert.equal(routeText(["X.1"], {}), "X.1");
});
test("node picker: a region after a comma filters the hits", () => {
  assert.deepEqual(nodeQuery("copper, CN"), { q: "copper", region: "cn" });
  assert.deepEqual(nodeQuery("copper"), { q: "copper", region: null });
  assert.deepEqual(nodeQuery("copper, "), { q: "copper, ", region: null });
  assert.deepEqual(nodeQuery(", CN"), { q: ", CN", region: null });
  assert.equal(inRegion({ region: "WA", region_label: "RoW Asia-Pacific" }, "row asia-pacific"), true);
  assert.equal(inRegion({ region: "US", region_label: "US" }, "cn"), false);
  assert.equal(inRegion({ region: "US", region_label: "US" }, null), true);
});
test("node picker: a comma inside a sector name still finds it", async () => {
  const nodes = [
    { region: "CN", region_label: "CN", sector: "Copper production" },
    { region: "DE", region_label: "DE", sector: "Copper production" },
    { region: "DE", region_label: "DE", sector: "Manufacture of motor vehicles, trailers and semi-trailers" },
  ];
  const sent: [string, number][] = [];
  const search = async (text: string, limit: number) => {
    sent.push([text, limit]);
    return nodes.filter((n) => n.sector.toLowerCase().includes(text.trim().toLowerCase())).slice(0, limit);
  };
  assert.deepEqual((await pickerHits("copper, CN", search)).map((n) => n.region), ["CN"]);
  const motor = await pickerHits("motor vehicles, trailers", search);
  assert.deepEqual(motor.map((n) => n.sector), ["Manufacture of motor vehicles, trailers and semi-trailers"]);
  assert.deepEqual(sent.slice(1), [["motor vehicles", 100], ["motor vehicles, trailers", 20]]);
});
test("shocks portfolio lens line", () => {
  assert.equal(lensLine("output", -8.2277), "Portfolio output change \u22128.23%");
  assert.equal(lensLine("price", 0.0347), "Portfolio price change 0.03%");
  assert.equal(lensLine("price", null), "Portfolio price change —");
});
test("shocks view hash keeps the portfolio", () => {
  assert.equal(shockHash("CN.4", "P"), "#/valueChain/CN.4/shock/P");
  assert.equal(shockHash("CN.4", "P 1/x"), "#/valueChain/CN.4/shock/P%201%2Fx");
  assert.equal(shockHash("CN.4", ""), "#/valueChain/CN.4/shock");
});
test("nace link line names the code and scheme", () => {
  assert.equal(naceLinkLine({ source: "nace", code: "07.29", code_scheme: "nace2" }), "Linked by NACE 07.29");
  assert.equal(naceLinkLine({ source: "nace", code: "2710", code_scheme: "isic4" }), "Linked by ISIC 2710");
  assert.equal(naceLinkLine({ source: "code", code: "07.29", code_scheme: "nace2" }), "");
});
test("link panel node line and nace21 scheme", () => {
  assert.equal(nodeLine({ region_label: "CN", sector: "Mining of copper ores and concentrates", weight: 0.7143 }), "CN · Mining of copper ores and concentrates 71.4%");
  assert.equal(naceLinkLine({ source: "nace", code: "07.29", code_scheme: "nace21" }), "Linked by NACE 07.29");
});
test("AC-51: a stored rule loaded into editor rows and saved unchanged is sent back as it was", () => {
  const split = { kind: "split" as const, parts: [{ sectors: ["Cultivation of wheat", "Cultivation of paddy rice"], share: 0.35 }, { sectors: ["Manufacture of machinery"], share: 0.65 }] };
  assert.deepEqual(split.parts.map((p) => rowToPart("split", partToRow(p))), split.parts);
  const nodes = [{ region: "CN", sector: "Mining", share: 0.07 }, { region: "DE", sector: "Steel", share: 0.93 }];
  assert.deepEqual(nodes.map((p) => rowToPart("nodes", partToRow(p))), nodes);
});
