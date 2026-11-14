import test from "node:test";
import assert from "node:assert/strict";
import { entryTab } from "../src/lib/nav.ts";
import { phaseAt, depthBucket } from "../src/lib/landingMotion.ts";

// Night Desk release 5 (docs/superpowers/specs/2026-11-09-night-desk-landing-design.md).
test("r5_ac1", () => { for (const h of ["", "#", "#/", "#/welcome"]) assert.equal(entryTab(h), "welcome", h); });
test("r5_ac2", () => { for (const h of ["#/home", "#/review/extraction/r1", "#/argus", "#/nonsense"]) assert.equal(entryTab(h), null, h); });
test("phase_boundaries", () => {
  // Landing brand refresh AC-1 (docs/superpowers/specs/2026-11-14-landing-brand-refresh-design.md): the 24 s six-phase loop.
  const p = (ms: number) => { const r = phaseAt(ms); return [r.phase, Math.round(r.t * 100) / 100]; };
  assert.deepEqual(p(0), ["network", 0]);
  assert.deepEqual(p(2500), ["network", 0.5]);
  assert.deepEqual(p(5000), ["gather", 0]);
  assert.deepEqual(p(7000), ["gather", 0.5]);
  assert.deepEqual(p(9000), ["orb", 0]);
  assert.deepEqual(p(11000), ["orb", 0.5]);
  assert.deepEqual(p(13000), ["emerge", 0]);
  assert.deepEqual(p(16500), ["formed", 0]);
  assert.deepEqual(p(18500), ["formed", 0.5]);
  assert.deepEqual(p(20500), ["dissolve", 0]);
  assert.deepEqual(p(24000), ["network", 0]);
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
// Landing brand refresh (docs/superpowers/specs/2026-11-14-landing-brand-refresh-design.md).
// AC-12a replaces text_backdrop_solid_behind_intro: the intro is now see-through.
const css = async () => read("../src/index.css");
const rule = (src: string, sel: string) => {
  const i = src.indexOf(sel + " {");
  assert.ok(i >= 0, sel);
  return src.slice(i, src.indexOf("}", i));
};
const darkBlocks = (src: string) => [src.slice(src.indexOf("@media (prefers-color-scheme: dark)"), src.indexOf(':root[data-theme="dark"]')), src.slice(src.indexOf(':root[data-theme="dark"]'), src.indexOf("}", src.indexOf(':root[data-theme="dark"]')))];
const rootBlock = (src: string) => src.slice(src.indexOf(":root {"), src.indexOf("}", src.indexOf(":root {")));
const landingRules = (src: string) => src.match(/\.landing[^{]*\{[^}]*\}/g) ?? [];
test("ac4_brand_apex", async () => {
  const c = await css();
  assert.match(rootBlock(c), /--brand-apex: #ea4c14;/);
  for (const b of darkBlocks(c)) assert.match(b, /--brand-apex: #ff6a2b;/);
});
test("ac5_orb_token", async () => {
  const c = await css();
  assert.match(rootBlock(c), /--orb: #ea4c14;/);
  for (const b of darkBlocks(c)) assert.match(b, /--orb: #ff6a2b;/);
});
test("ac6_no_signal_on_landing", async () => {
  for (const r of landingRules(await css())) assert.doesNotMatch(r, /--hi|--await-edge/, r);
});
test("ac7_no_colour_literals_in_landing_css", async () => {
  for (const r of landingRules(await css())) assert.doesNotMatch(r, /#[0-9a-fA-F]{3,8}\b|rgba?\(|oklch\(/, r);
});
test("ac12a_see_through_intro", async () =>
  assert.match(rule(await css(), ".landing-main"), /linear-gradient\(90deg, color-mix\(in srgb, var\(--bg\) 40%, transparent\) 55%, transparent\)/));
test("ac12b_text_halo", async () => {
  const c = await css();
  assert.match(c, /\.landing-main h1, \.landing-main p \{[^}]*text-shadow: 0 0 14px var\(--bg\), 0 0 4px var\(--bg\)/);
});
test("ac12c_see_through_intro_narrow", async () => {
  const c = await css();
  const m = c.slice(c.lastIndexOf("@media (max-width: 700px)"));
  assert.match(rule(m, ".landing-main"), /linear-gradient\(180deg, color-mix\(in srgb, var\(--bg\) 40%, transparent\) 70%, transparent\)/);
});
test("ac15a_serif_headline", async () => {
  const h = rule(await css(), ".landing-main h1");
  assert.match(h, /font-family: "Source Serif 4"/);
  assert.match(h, /font-weight: 500/);
  assert.match(h, /letter-spacing: -0\.01em/);
});
test("ac15b_headline_size_unchanged", async () => {
  const h = rule(await css(), ".landing-main h1");
  assert.match(h, /font-size: clamp\(2\.5rem, 2rem \+ 3vw, 4\.2rem\)/);
  assert.match(h, /line-height: 1\.02/);
});
test("ac16_promise_squares", async () => {
  const b = rule(await css(), ".landing-promises b::before");
  for (const d of ["width: 6px", "height: 6px", "border-radius: 0", "background: var(--text)"]) assert.ok(b.includes(d), d);
});
test("resize_rebuild_is_throttled", async () => assert.match(await read("../src/components/LandingCanvas.tsx"), /requestAnimationFrame\(\(\) => \{\s*resizeFrame = 0;/));
test("zero_size_canvas_does_not_crash", async () => assert.ok((await read("../src/components/LandingCanvas.tsx")).includes("if (!W || !H) return;")));
const landingTsx = async () => read("../src/pages/Landing.tsx");
test("ac3_lockup_svg", async () => {
  const src = await landingTsx();
  assert.ok(src.includes('role="img"') && src.includes('aria-label="ARP"') && src.includes("var(--brand-apex)"));
  assert.doesNotMatch(src, /<\/svg>\s*ARP\b/);
});
test("ac14_copy", async () => {
  const src = await landingTsx();
  assert.ok(src.includes("Company research and stewardship at scale."));
  assert.ok(src.includes("Leveraging expert judgement through Agents."));
  assert.ok(!src.includes("Agents propose."));
});
test("ac7_no_colour_literals_in_landing_tsx", async () => assert.doesNotMatch(await landingTsx(), /#[0-9a-fA-F]{3,8}\b|rgba?\(|oklch\(/));
test("ac6_no_signal_in_landing_tsx", async () => assert.doesNotMatch(await landingTsx(), /--hi\b|--hi-ink|--await-edge/));
const canvasTsx = async () => read("../src/components/LandingCanvas.tsx");
test("ac7b_canvas_colours_from_tokens", async () => {
  const src = await canvasTsx();
  assert.doesNotMatch(src, /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(|oklch\(/);
  assert.ok(src.includes("--orb") && src.includes("--brand-apex"));
});
test("ac6_no_signal_in_canvas", async () => assert.doesNotMatch(await canvasTsx(), /--hi\b|--hi-ink|--await-edge/));
test("theme_follows_live", async () => {
  const src = await canvasTsx();
  for (const s of ["MutationObserver", 'attributeFilter: ["data-theme"]', "prefers-color-scheme: dark"]) assert.ok(src.includes(s), s);
});
test("reduced_motion_single_frame", async () => assert.match(await canvasTsx(), /if \(reduce\) \{\s*still\(\);\s*return cleanup;/));
// Final review: a zero-size canvas left colours unread and draw() threw on addColorStop("").
test("draw_skips_zero_size_canvas", async () => assert.match(await canvasTsx(), /const draw = \(t: number\) => \{\s*if \(!W \|\| !H\) return;/));
// Final review: the reduced-motion still frame must follow theme changes and resizes too.
test("reduced_motion_frame_follows_theme_and_resize", async () => {
  const src = await canvasTsx();
  assert.match(src, /readColours\(\);\s*if \(reduce\) still\(\);/);
  assert.match(src, /build\(\);\s*if \(reduce\) still\(\);/);
});
test("no_debug_global", async () => assert.ok(!(await canvasTsx()).includes("__arp")));
// Points slightly behind or in front of the orb have depth outside 0..1; every segment still gets a bucket.
test("depth_bucket_clamps_out_of_range_depth", () => {
  assert.equal(depthBucket(-0.1), 0);
  assert.equal(depthBucket(1), 2);
  assert.equal(depthBucket(2.1), 3);
});
