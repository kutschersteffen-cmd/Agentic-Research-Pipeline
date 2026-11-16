import test from "node:test";
import assert from "node:assert/strict";
import { redirectHash } from "../src/lib/nav.ts";

test("redirectHash sends each removed screen, and any path under it, to its replacement", () => {
  assert.equal(redirectHash("#/dashboard"), "#/home");
  assert.equal(redirectHash("#/dashboard/x"), "#/home");
  assert.equal(redirectHash("#/tape"), "#/review");
  assert.equal(redirectHash("#/identity"), "#/argus/new");
  assert.equal(redirectHash("#/identity/abc"), "#/argus/new");
  assert.equal(redirectHash("#/discovery"), "#/argus/new");
});

test("redirectHash sends the old Extraction screens into the Argus flow (AC-62..64)", () => {
  assert.equal(redirectHash("#/extraction"), "#/argus");
  assert.equal(redirectHash("#/extraction/companies/auto"), "#/argus");
  assert.equal(redirectHash("#/argusUniverse"), "#/argus/new");
  assert.equal(redirectHash("#/discovery/x"), "#/argus/new");
  assert.equal(redirectHash("#/transitionPlan"), "#/argus/new/transition_plan");
  assert.equal(redirectHash("#/transitionPlan/x"), "#/argus/new/transition_plan");
  assert.equal(redirectHash("#/argusWalkthrough"), null);  // the walkthrough stays
  assert.equal(redirectHash("#/argus/new"), null);
});

test("redirectHash leaves every other hash alone", () => {
  assert.equal(redirectHash("#/review"), null);
  assert.equal(redirectHash("#/dashboardx"), null);
  assert.equal(redirectHash(""), null);
});

// App-wide top bar (2026-11-15-app-wide-top-bar spec) retired the sidebar tests: NAV_GROUPS and currentNavIds went with
// the sidebar. The Workspaces menu's links are checked in workspaceCard.test.ts (pr1_menu_items).

