import test from "node:test";
import assert from "node:assert/strict";
import { entryTab } from "../src/lib/nav.ts";
import { phaseAt } from "../src/lib/landingMotion.ts";

// Night Desk release 5 (docs/superpowers/specs/2026-11-09-night-desk-landing-design.md).
test("r5_ac1", () => { for (const h of ["", "#", "#/", "#/welcome"]) assert.equal(entryTab(h), "welcome", h); });
test("r5_ac2", () => { for (const h of ["#/home", "#/review/extraction/r1", "#/argus", "#/nonsense"]) assert.equal(entryTab(h), null, h); });
test("phase_boundaries", () => {
  const p = (ms: number) => { const r = phaseAt(ms); return [r.phase, Math.round(r.t * 100) / 100]; };
  assert.deepEqual(p(0), ["network", 0]);
  assert.deepEqual(p(2000), ["network", 0.5]);
  assert.deepEqual(p(5000), ["light", 0.5]);
  assert.deepEqual(p(10000), ["stream", 0.5]);
  assert.deepEqual(p(16000), ["formed", 0.5]);
  assert.deepEqual(p(20000), ["dissolve", 0.5]);
  assert.deepEqual(p(22000), ["network", 0]);
});
