import test from "node:test";
import assert from "node:assert/strict";
import { NAV_GROUPS, currentNavIds, navCount, redirectHash } from "../src/lib/nav.ts";

test("redirectHash sends each removed screen, and any path under it, to its replacement", () => {
  assert.equal(redirectHash("#/dashboard"), "#/home");
  assert.equal(redirectHash("#/dashboard/x"), "#/home");
  assert.equal(redirectHash("#/tape"), "#/review");
  assert.equal(redirectHash("#/identity"), "#/extraction/identify");
  assert.equal(redirectHash("#/identity/abc"), "#/extraction/identify");
  assert.equal(redirectHash("#/discovery"), "#/extraction/documents");
});

test("redirectHash leaves every other hash alone", () => {
  assert.equal(redirectHash("#/review"), null);
  assert.equal(redirectHash("#/dashboardx"), null);
  assert.equal(redirectHash(""), null);
});

test("the sidebar lists exactly the approved links, in order, under the approved labels", () => {
  assert.deepEqual(
    NAV_GROUPS.flatMap((g) => g.ids),
    ["home", "review", "stewardiq", "argus", "transitionIntel", "rdLab", "dataHub", "reporting", "arcade"],
  );
  assert.deepEqual(NAV_GROUPS.map((g) => g.label), [null, "Needs you", "Workspaces", "Output", null]);
});

test("currentNavIds marks a sidebar link only for its own screen", () => {
  assert.deepEqual(currentNavIds("argus"), ["argus"]);
  assert.deepEqual(currentNavIds("review"), ["review"]);
  for (const off of ["search", "history", "argusUniverse", "transitionPlan"]) assert.deepEqual(currentNavIds(off), [], off);
});

test("navCount shows the review badge and nothing else", () => {
  assert.equal(navCount("review", { review: 1 }), 1);
  assert.equal(navCount("argus", { review: 1 }), 0);
  assert.equal(navCount("review", null), 0);
});
