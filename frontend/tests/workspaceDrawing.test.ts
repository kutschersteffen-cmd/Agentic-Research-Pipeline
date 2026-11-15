import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { drawing, DRAWING_IDS } from "../src/lib/workspaceDrawing.ts";

// Start page simplified (docs/superpowers/specs/2026-11-15-start-page-simplified-design.md).
test("sp_ac13a_one_accent_at_most", () => {
  for (const id of DRAWING_IDS) {
    assert.equal(drawing(id, null).filter((s) => s.accent).length, 0, id);
    assert.equal(drawing(id, "wait").filter((s) => s.accent).length, 1, id);
    assert.equal(drawing(id, "now").filter((s) => s.accent).length, 1, id);
  }
});
test("sp_ac13b_five_different_drawings", () => {
  const keys = DRAWING_IDS.map((id) => JSON.stringify(drawing(id, null)));
  assert.equal(new Set(keys).size, 5);
  assert.deepEqual([...DRAWING_IDS].sort(), ["dataHub", "argus", "rdLab", "stewardiq", "transitionIntel"].sort());
});
test("sp_ac14_no_colour_literals_in_drawings", () => {
  for (const f of ["../src/lib/workspaceDrawing.ts", "../src/components/WorkspaceDrawing.tsx"]) {
    const src = readFileSync(new URL(f, import.meta.url), "utf8");
    assert.doesNotMatch(src, /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(|oklch\(|["'\s:](white|black|red|blue|green|orange|gray|grey)["';\s]/, f);
  }
});
