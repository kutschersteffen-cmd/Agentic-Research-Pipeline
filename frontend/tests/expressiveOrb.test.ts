import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { OrbClock, QualityRule, nextColour, pixelRatio, pinnedLevel, startLevel, type OrbLevel } from "../src/lib/orbMotion.ts";

// expressive-ui-orb slice 1 (docs/superpowers/specs/2026-11-22-expressive-ui-orb.md).

const feed = (from: OrbLevel, gaps: [number, boolean?][]) => {
  const r = new QualityRule(from);
  for (const [g, afterPause] of gaps) r.add(g, afterPause);
  return r.level;
};
const n = (count: number, ms: number): [number][] => Array.from({ length: count }, () => [ms]);

test("ac28_quality_rule", () => {
  assert.equal(feed("high", n(60, 30)), "high");
  assert.equal(feed("high", n(60, 34)), "medium");
  assert.equal(feed("low", n(60, 45)), "low");
  assert.equal(feed("low", n(60, 51)), "still");
  assert.equal(feed("high", [...n(59, 20), [5000, true]]), "high");
  assert.equal(feed("high", [...n(59, 20), [5000, false]]), "medium"); // the gap counts as 1000 ms: mean 36.3 ms
});
test("quality_rule_steps_one_level_at_a_time_and_never_up", () => {
  assert.equal(feed("high", n(120, 40)), "low");
  assert.equal(feed("medium", n(60, 34)), "low");
  assert.equal(feed("medium", n(600, 5)), "medium");
  assert.equal(feed("still", n(60, 5)), "still");
  assert.equal(feed("high", n(180, 100)), "still");
});

test("stored_levels", () => {
  assert.equal(pinnedLevel("low"), "low");
  assert.equal(pinnedLevel("fast"), null);
  assert.equal(pinnedLevel(null), null);
  assert.equal(startLevel("medium", "still"), "medium"); // a pin wins over the session
  assert.equal(startLevel("nonsense", "low"), "low");
  assert.equal(startLevel(null, null), "high");
  assert.equal(startLevel(null, "bogus"), "high");
});
test("pixel_ratio_per_quality", () => {
  assert.equal(pixelRatio("low", 2, 600, 600), 0.75);
  assert.equal(pixelRatio("medium", 2, 600, 600), 1);
  assert.equal(pixelRatio("high", 3, 600, 600), 2);
  assert.ok(pixelRatio("high", 2, 2000, 2000) * pixelRatio("high", 2, 2000, 2000) * 4e6 <= 3.4e6 + 1);
});

// Run a clock in steps of `dt` seconds for `secs`, recording each phase change.
const run = (c: OrbClock, secs: number, dt = 0.05) => {
  const seen: string[] = [];
  for (let t = 0; t < secs; t += dt) {
    const before = c.phase;
    c.tick(dt);
    if (c.phase !== before) seen.push(c.phase);
  }
  return seen;
};
test("intro_timeline", () => {
  const c = new OrbClock(true, () => 0.5);
  assert.equal(c.phase, "assembling");
  run(c, 2.55);
  assert.equal(c.phase, "assembling");
  run(c, 0.1);
  assert.equal(c.phase, "locked");
  run(c, 1);
  assert.equal(c.phase, "idle");
  assert.equal(new OrbClock(false).phase, "idle");
});
test("click_transforms_and_moves_the_colour_on", () => {
  const c = new OrbClock(false, () => 0.99);
  assert.equal(c.click(), true);
  assert.equal(c.phase, "folding");
  assert.equal(c.click(), false, "clicks during a transformation are ignored");
  assert.deepEqual(run(c, 3.4), ["realigning", "unfolding", "locked", "idle"]);
  assert.equal(c.colour, "ice");
  const order = [c.colour];
  for (let i = 0; i < 3; i++) { c.click(); run(c, 3.4); order.push(c.colour); }
  assert.deepEqual(order, ["ice", "ember", "mint", "gold"]);
  assert.equal(nextColour("mint"), "gold");
});
test("transforms_by_itself_after_8_to_11_s_idle", () => {
  const early = new OrbClock(false, () => 0);
  run(early, 7.9);
  assert.equal(early.phase, "idle");
  run(early, 0.2);
  assert.equal(early.phase, "folding");
  const late = new OrbClock(false, () => 0.999);
  run(late, 10.9);
  assert.equal(late.phase, "idle");
  run(late, 0.2);
  assert.equal(late.phase, "folding");
});
test("long_frame_gaps_count_as_250_ms", () => {
  const c = new OrbClock(true);
  c.tick(5);
  assert.equal(c.phase, "assembling");
});
test("speaking_stops_the_timer_and_restarts_it_from_zero", () => {
  const c = new OrbClock(false, () => 0);
  run(c, 7);
  c.setSpeaking(true);
  assert.equal(c.phase, "speaking");
  assert.equal(c.click(), false);
  run(c, 20);
  assert.equal(c.phase, "speaking");
  c.setSpeaking(false);
  assert.equal(c.phase, "idle");
  run(c, 7.5);
  assert.equal(c.phase, "idle", "the timer started again from zero");
  const during = new OrbClock(true);
  during.setSpeaking(true);
  assert.equal(during.phase, "assembling", "speaking waits until the Orb is otherwise idle");
  run(during, 4);
  assert.equal(during.phase, "speaking");
});

// AC-30: DESIGN.md carries the amendment.
const flat = (s: string) => s.replace(/\*/g, "").replace(/\s+/g, " ");
const design = flat(readFileSync(new URL("../../DESIGN.md", import.meta.url), "utf8"));
const SENTENCES = [
  "There is one theme: black. Every component reads its colours from the same tokens.",
  "Black ground, ink accent for controls, amber reserved for 'waiting on a person'.",
  "The Orb, a gold hologram, stands for the agents; it is the only place where colour is spectacle.",
  "Brand orange (#ff6a2b) appears in two places only: the logo apex and the square of the landing caption. It never appears elsewhere in the interface, so it cannot be mistaken for the amber signal.",
  "The Orb is gold and morphs through ice, ember and mint. These four colours live only inside the Orb's canvas and its phase label. They carry no meaning: they are not status and not the signal. Nothing outside the Orb may use them, and the Orb never uses `--hi`.",
  "The Orb's gold is not amber and is exempt (see The Orb Colour Rule).",
  "Pixel Font: Geist Pixel Square, for the landing headline, the start-page greeting and the five workspace titles only",
  "(Geist Pixel Square 400, clamp(52px → 104px), 0.92): the start-page greeting; the workspace titles use the same face at clamp(48px → 92px)",
  "The serif is for text quoted from a source document (the evidence paper). Nothing else uses it.",
  "Pixel type marks the three places where ARP presents itself: the landing headline, the greeting and a workspace's title. Never set running text, tables or controls in it.",
  "Glows are status light, not elevation: a start card or process panel that runs or waits, its figure area and the lit part of its drawing glow in the status colour. Nothing else glows.",
  "Five elements",
  "The visual for ARP's agents: a gold holographic sphere whose parts turn in steps, fold and lock. It appears on the landing page, the start page, a workspace's Ask ARP card and the Agent screen, once per page. Hover previews the next colour, a click transforms it. Without WebGL, under reduced motion or on a slow GPU it is a still picture. Never draw streams into or out of it.",
  "Processes and steps are shown as a rail of 10px segments, 3px apart: solid ink = done, blue and flowing = running, amber and breathing = waiting on you, red = failed, outlined = idle, dashed = unknown or planned. Under reduced motion nothing flows or breathes.",
  "The lit element is out of place while lit (lifted or taller) and moves once, in 850ms, when the status changes. Nothing else in a drawing moves.",
  "the theme depends on it",
  "Don't use brand orange anywhere but the logo apex and the landing caption.",
  "Don't use the Orb's colours outside the Orb.",
  "Don't animate a drawing while its status is unchanged.",
  "# Design System: Agentic Research Platform",
  "### The Orb",
  "### Status Rail",
];
test("ac30_design_md_amendment", () => {
  for (const t of SENTENCES) assert.ok(design.includes(flat(t)), t);
  for (const t of ["in light and dark", "the landing animation's orb glow", "in both themes", "both themes depend on it"]) assert.ok(!design.includes(t), t);
});

// The Orb's wiring that the browser rows rely on.
const src = (p: string) => readFileSync(new URL(p, import.meta.url), "utf8");
test("orb_scene_is_loaded_on_demand", () => {
  const orb = src("../src/components/Orb.tsx");
  assert.match(orb, /import\("\.\.\/orb\/orbScene"\)/);
  assert.doesNotMatch(orb, /^import (?!type )[^;]*from "(three|\.\.\/orb\/orbScene)"/m);
  assert.match(orb, /import type \{ OrbScene \} from "\.\.\/orb\/orbScene"/);
});
test("three_pinned_exactly", () => {
  const pkg = JSON.parse(src("../package.json"));
  assert.match(pkg.dependencies.three, /^0\.(1[7-9]\d|[2-9]\d\d)\.\d+$/);
});
test("pixel_font_self_hosted", () => {
  const css = src("../src/index.css");
  assert.match(css, /@font-face \{\s*font-family: "Geist Pixel Square";\s*src: url\("\.\/assets\/fonts\/GeistPixel-Square\.woff2"\) format\("woff2"\);[^}]*font-display: swap;/);
  assert.equal(readFileSync(new URL("../src/assets/fonts/GeistPixel-Square.woff2", import.meta.url)).length, 28540);
  assert.match(src("../src/assets/fonts/LICENSE.txt"), /SIL Open Font License/);
});
test("still_picture", () => {
  const webp = readFileSync(new URL("../src/assets/orb-still.webp", import.meta.url));
  assert.ok(webp.length <= 80000, `${webp.length} bytes`);
  assert.equal(webp.subarray(8, 12).toString("ascii"), "WEBP");
});
test("ac10_tab_title_and_no_theme_script", () => {
  const html = src("../index.html");
  assert.match(html, /<title>Agentic Research Platform<\/title>/);
  assert.doesNotMatch(html, /arp\.theme|data-theme|dataset\.theme/);
});
