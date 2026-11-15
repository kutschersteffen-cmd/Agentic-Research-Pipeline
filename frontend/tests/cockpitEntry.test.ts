import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { cockpitDrawing, drawing, DRAWING_IDS } from "../src/lib/workspaceDrawing.ts";

// Stewardship cockpit PR 3: the start page's Cockpit entry.
test("the cockpit drawing never carries the accent and differs from every workspace drawing", () => {
  const shapes = cockpitDrawing();
  assert.ok(shapes.length > 0);
  assert.equal(shapes.filter((s) => s.accent).length, 0);
  const own = JSON.stringify(shapes);
  for (const id of DRAWING_IDS) assert.notEqual(own, JSON.stringify(drawing(id, null)), id);
});

test("the start page links the cockpit outside the five workspace cards", () => {
  const src = readFileSync(new URL("../src/pages/ProcessHub.tsx", import.meta.url), "utf8");
  const start = src.slice(src.indexOf("export function StartPage"));
  assert.match(start, /<a className="hub-entry" href="#\/stewardiq\/cockpit">/);
  assert.doesNotMatch(start, /className="hub-card[^"]*" href="#\/stewardiq\/cockpit"/);
});
