import { test } from "node:test";
import assert from "node:assert/strict";
import {
  chooseUniverse, DEMO_BANNER, nextIndexId, pickerFields, universeBanner, universeOption, withUniverse,
  type UniverseChoice,
} from "../src/lib/indexBuilder.ts";
import type { IndexStartingUniverseDetail } from "../src/types.ts";

// index-starting-universe, PR 2: the Starting universe card on Index Construction, API mocked.

const DEMO = { universe_id: "demo", label: "Built-in demo universe (60 synthetic companies)", kind: "demo" as const, as_of_date: null };
const DAX = { universe_id: "file:DAX", label: "DAX.xlsx", kind: "file" as const, as_of_date: "2026-11-02" };
const CATALOGUE_FIELDS = { metrics: ["adv_3m", "float_mcap", "ghg_intensity"], flags: ["norms_violation"], categories: ["country", "sector"] };
const DAX_DETAIL: IndexStartingUniverseDetail = {
  ...DAX,
  company_count: 40,
  notes: ["Starting universe: DAX.xlsx, holdings as of 2026-11-02, 40 companies."],
  fields: { metrics: ["float_mcap", "free_float_factor", "price", "shares_outstanding"], flags: [], categories: ["country", "sector"] },
};
const ON_DEMO: UniverseChoice = { detail: null, error: null };
const loadsDax = async (id: string) => {
  assert.equal(id, "file:DAX");
  return DAX_DETAIL;
};
const fails = async () => {
  throw new Error("500: boom");
};
// The body the page sends on Preview (IndexBuilder runReview), before the universe is added.
const PREVIEW = { index_id: "demo_index", review_date: "2026-11-13", persist: false, use_prior_state: true, decision_snapshot_ids: [] };

test("AC-51, AC-52, AC-68: the select's options read as the label plus kind and date", () => {
  assert.equal(universeOption(DEMO), "Built-in demo universe (60 synthetic companies)");
  assert.equal(universeOption(DAX), "DAX.xlsx (holdings file, 2026-11-02)");
  assert.equal(
    universeOption({ universe_id: "portfolio:p1", label: "My fund", kind: "portfolio", as_of_date: "2026-10-31" }),
    "My fund (portfolio, 2026-10-31)",
  );
});

test("AC-63, AC-64, AC-65: a failed DAX load shows the error and keeps the demo universe and the catalogue's fields", async () => {
  const after = await chooseUniverse(ON_DEMO, "file:DAX", fails);
  assert.match(after.error!, /boom/);
  assert.equal(after.detail, null);
  assert.deepEqual(pickerFields(after, CATALOGUE_FIELDS).metrics, CATALOGUE_FIELDS.metrics);
  assert.equal(universeBanner(after.detail), DEMO_BANNER);
});

test("a failed load of another file keeps the universe loaded before it", async () => {
  const onDax = await chooseUniverse(ON_DEMO, "file:DAX", loadsDax);
  const after = await chooseUniverse(onDax, "file:MSCI_World", fails);
  assert.equal(after.detail, DAX_DETAIL);
});

test("AC-54, AC-61: DAX's fields replace the catalogue's; choosing the demo again restores them without a request", async () => {
  const onDax = await chooseUniverse(ON_DEMO, "file:DAX", loadsDax);
  assert.deepEqual(pickerFields(onDax, CATALOGUE_FIELDS), DAX_DETAIL.fields);
  const back = await chooseUniverse(onDax, "demo", fails);
  assert.deepEqual(back, { detail: null, error: null });
  assert.deepEqual(pickerFields(back, CATALOGUE_FIELDS), CATALOGUE_FIELDS);
});

test("AC-55, AC-66: the proposed index id follows the universe; a typed one stays", () => {
  assert.equal(nextIndexId("demo_index", "demo", "file:DAX"), "dax_index");
  assert.equal(nextIndexId("my_index", "demo", "file:DAX"), "my_index");
  assert.equal(nextIndexId("demo_index", "demo", "file:MSCI_World"), "msci_world_index");
  assert.equal(nextIndexId("demo_index", "demo", "portfolio:p1"), "p1_index");
  assert.equal(nextIndexId("dax_index", "file:DAX", "file:MSCI_World"), "msci_world_index");
  assert.equal(nextIndexId("dax_index", "file:DAX", "demo"), "demo_index");
});

test("AC-67: a Preview on DAX sends universe file:DAX and no candidates", async () => {
  const body = withUniverse(PREVIEW, await chooseUniverse(ON_DEMO, "file:DAX", loadsDax));
  assert.equal(body.universe, "file:DAX");
  assert.ok(!("candidates" in body));
});

test("AC-69: a Preview on the demo universe sends neither universe nor candidates", () => {
  const body = withUniverse(PREVIEW, ON_DEMO);
  assert.deepEqual(body, PREVIEW);
  assert.ok(!("universe" in body) && !("candidates" in body));
});

test("AC-57, AC-58, AC-59: the banner names a loaded universe instead of the demo warning", () => {
  assert.equal(
    universeBanner(DAX_DETAIL),
    "Starting universe: DAX.xlsx (holdings as of 2026-11-02, 40 companies). Sizes are a weight proxy and ESG values, where present, are simulated. The results describe no real index.",
  );
  assert.ok(!universeBanner(DAX_DETAIL).startsWith("Demo data:"));
  assert.ok(universeBanner(null).startsWith("Demo data:"));
});
