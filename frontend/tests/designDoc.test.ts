import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

// App-wide top bar, PR 1, AC-24: DESIGN.md describes the top bar and the workspace row, not the sidebar.
test("pr1_ac24_design_md", () => {
  const up = ["../../", "../../../", "../../../../"].map((p) => new URL(`${p}DESIGN.md`, import.meta.url));
  const design = readFileSync(up.find((u) => existsSync(u)) ?? up[0], "utf8");
  assert.ok(design.includes("**Top bar:**"), "Top bar entry");
  assert.ok(design.includes("**Workspace row:**"), "Workspace row entry");
  assert.ok(!design.includes("**Sidebar:**"), "no Sidebar entry");
  assert.ok(!design.includes("**Mobile / tablet:**"), "no Mobile / tablet entry");
});
