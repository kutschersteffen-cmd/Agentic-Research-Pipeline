import test from "node:test";
import assert from "node:assert/strict";
import { WORKSPACES, rowLinks, workspaceOfRoute } from "../src/lib/processes.ts";

// App-wide top bar, PR 1 (docs/superpowers/specs/2026-11-15-app-wide-top-bar-design.md).
test("pr1_ac10_workspace_of_route", () => {
  const cases: [string, string | null][] = [
    ["#/argus", "argus"], ["#/argus/abc123", "argus"], ["#/argus/new", "argus"],
    ["#/argus/new/transition_plan", "transitionIntel"], ["#/voting", "stewardiq"], ["#/library", "dataHub"],
    ["#/review", null], ["#/reporting", null], ["#/home", null], ["#/arcade", null], ["#/nosuch", null],
    ["#/review/extraction/x", null],
  ];
  for (const [h, want] of cases) assert.equal(workspaceOfRoute(h), want, h);
});
test("pr1_row_links", () => {
  const argus = WORKSPACES.find((w) => w.id === "argus")!;
  const links = rowLinks(argus);
  assert.deepEqual(links[0], ["#/argus", "Argus"]);
  assert.deepEqual(links.slice(1), [["#/argus/new", "New extraction"], ["#/xbrl", "XBRL Facts"]]); // ui-trim-workspaces: the row, not every screen
  const ti = WORKSPACES.find((w) => w.id === "transitionIntel")!;
  assert.deepEqual(rowLinks(ti)[0], ["#/transitionIntel", "Transition Intel"]);
});
