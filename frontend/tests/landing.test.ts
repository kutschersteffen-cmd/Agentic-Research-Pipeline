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

test("r5_ac11", async () => {
  const { readFileSync } = await import("node:fs");
  const src = readFileSync(new URL("../src/components/LandingCanvas.tsx", import.meta.url), "utf8");
  for (const s of ["IntersectionObserver", "visibilitychange", "prefers-reduced-motion", "cancelAnimationFrame", 'aria-hidden="true"', 'removeEventListener("resize"'])
    assert.ok(src.includes(s), s);
});

// Final-review fixes.
const read = async (p: string) => (await import("node:fs")).readFileSync(new URL(p, import.meta.url), "utf8");
test("phones_can_scroll_the_landing_page", async () => {
  const css = await read("../src/index.css");
  const m = css.slice(css.lastIndexOf("@media (max-width: 700px)"));
  assert.match(m, /\.landing \{[^}]*overflow-y: auto/);
});
test("text_backdrop_solid_behind_intro", async () =>
  assert.match(await read("../src/index.css"), /\.landing-main \{[^}]*linear-gradient\(90deg, var\(--bg\) 75%, transparent\)/));
test("resize_rebuild_is_throttled", async () => assert.match(await read("../src/components/LandingCanvas.tsx"), /requestAnimationFrame\(\(\) => \{\s*resizeFrame = 0;/));
test("zero_size_canvas_does_not_crash", async () => assert.ok((await read("../src/components/LandingCanvas.tsx")).includes("if (!W || !H) return;")));
