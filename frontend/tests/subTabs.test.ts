import test from "node:test";
import assert from "node:assert/strict";
import { resolveSubTab, SUB_TABS } from "../src/lib/subTabs.ts";

const TABS = [{ id: "dashboards" }, { id: "monitoring" }, { id: "profiles" }] as const;

test("resolveSubTab keeps a known id", () => {
  assert.equal(resolveSubTab("monitoring", TABS), "monitoring");
});

test("resolveSubTab maps the removed pivot, superset and genbi ids to dashboards", () => {
  assert.equal(resolveSubTab("genbi", TABS), "dashboards");
  assert.equal(resolveSubTab("pivot", TABS), "dashboards");
  assert.equal(resolveSubTab("superset", TABS), "dashboards");
});

test("resolveSubTab falls back to dashboards for unknown or missing ids", () => {
  assert.equal(resolveSubTab("nope", TABS), "dashboards");
  assert.equal(resolveSubTab(undefined, TABS), "dashboards");
});

test("the standard sub-tab is gone and the default is dashboards", () => {
  assert.ok(!SUB_TABS.some((t) => t.id === "standard"));
  assert.equal(SUB_TABS[0].id, "dashboards");
  assert.equal(resolveSubTab("standard", SUB_TABS), "dashboards");
  assert.equal(resolveSubTab(undefined, SUB_TABS), "dashboards");
});

test("the governance sub-tab is gone and its id falls back to the default", () => {
  assert.ok(!SUB_TABS.some((t) => t.id === "governance"));
  assert.equal(resolveSubTab("governance", SUB_TABS), "dashboards");
});
