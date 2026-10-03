import test from "node:test";
import assert from "node:assert/strict";
import { resolveSubTab } from "../src/lib/subTabs.ts";

const TABS = [{ id: "standard" }, { id: "monitoring" }, { id: "dashboards" }] as const;

test("resolveSubTab keeps a known id", () => {
  assert.equal(resolveSubTab("monitoring", TABS), "monitoring");
});

test("resolveSubTab maps the removed pivot, superset and genbi ids to dashboards", () => {
  assert.equal(resolveSubTab("genbi", TABS), "dashboards");
  assert.equal(resolveSubTab("pivot", TABS), "dashboards");
  assert.equal(resolveSubTab("superset", TABS), "dashboards");
});

test("resolveSubTab falls back to standard for unknown or missing ids", () => {
  assert.equal(resolveSubTab("nope", TABS), "standard");
  assert.equal(resolveSubTab(undefined, TABS), "standard");
});
