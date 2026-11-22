import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// UI polish 2: the owner's Linear picks (docs/superpowers/specs/2026-11-16-ui-polish-2-linear-design.md).
const css = readFileSync(new URL("../src/index.css", import.meta.url), "utf8");
const root = css.slice(css.indexOf(":root {"), css.indexOf("}", css.indexOf(":root {")));

test("p2_ac1_text2_token", () => {
  assert.ok(root.includes("--text-2: color-mix(in oklch, var(--text) 80%, var(--muted));"), "--text-2 in :root");
});
test("p2_ac4_tracking_tokens", () => {
  for (const t of ["--track-display: -0.025em;", "--track-title: -0.015em;", "--track-body: -0.008em;"]) assert.ok(root.includes(t), t);
});

test("p2_ac7_motion", () => {
  for (const t of ["--dur-fast: 100ms;", "--dur-slow: 240ms;", "--ease-out: cubic-bezier(0.25, 0.46, 0.45, 0.94);"]) assert.ok(root.includes(t), t);
  for (const m of css.matchAll(/transition:[^;]*;/g)) assert.doesNotMatch(m[0], /\b0\.15s|\b0\.4s/, m[0]);
  assert.match(css, /\.progress-bar-fill \{[^}]*transition: transform var\(--dur-slow\) var\(--ease-out\)/);
});
test("p2_ac8_wrap_smoothing", () => {
  assert.match(css, /:where\(h1, h2, h3, h4\) \{ text-wrap: balance; \}/);
  assert.match(css, /:where\(p, li, dd, figcaption\) \{ text-wrap: pretty; \}/);
  // One theme since expressive-ui-orb (Supersedes): the font-smoothing rule sits on body, once.
  assert.equal(css.split("-webkit-font-smoothing: antialiased").length - 1, 1);
  assert.match(css, /\nbody \{ -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; \}/);
});
test("p2_ac10_design_md", () => {
  const design = readFileSync(new URL("../../DESIGN.md", import.meta.url), "utf8");
  for (const t of ["--text-2", "--track-display", "--dur-fast", "--dur-slow", "--ease-out"]) assert.ok(design.includes(t), t);
});

// Final review: titles under 20px keep the 600 weight they had through `.card h2`.
test("p2_small_card_titles_keep_600", () => {
  for (const sel of [".decision-kpis h2", ".argus-schema-pick h2, .argus-schema-fields h2, .argus-run-list h2", ".cockpit-card-head h2"]) {
    const i = css.indexOf(`${sel} {`);
    assert.ok(i >= 0, sel);
    assert.match(css.slice(i, css.indexOf("}", i)), /font-weight: 600/, sel);
  }
});
// Final review: a meta line under a title is not the page intro, so it stays muted, not a lead.
test("p2_meta_lines_not_lead", () => {
  const src = (f: string) => readFileSync(new URL(`../src/pages/${f}`, import.meta.url), "utf8");
  assert.match(src("ThemeDossiers.tsx"), /<h1>\{dossier\.name\}<\/h1>\s*<p className="muted meta">/);
  assert.match(src("BarrierCellDetail.tsx"), /<h1>\{cell\.code\}[^\n]*\n\s*<p className="muted meta">/);
  assert.ok(css.includes(":where(.page, .page-body) > h1 + :is(.help-text, .muted):not(.meta) {"), "intro rule skips .meta");
});

test("p2_ac17_design_md", () => {
  const design = readFileSync(new URL("../../DESIGN.md", import.meta.url), "utf8");
  for (const e of ["**Tile strip:**", "**Filter chips:**", "**Phone tables:**"]) assert.ok(design.includes(e), e); // DESIGN.md entries are "**Name:**"
  const phone = design.slice(design.indexOf("**Phone tables:**"));
  assert.match(phone.slice(0, phone.indexOf("\n")), /card/);
});
test("p2_ac18_no_new_important", async (t) => {
  const { execSync } = await import("node:child_process");
  let diff: string;
  try {
    diff = execSync("git diff origin/main -- src/index.css", { cwd: new URL("..", import.meta.url), encoding: "utf8" });
  } catch {
    t.skip("origin/main not fetched"); // reported as skipped, never as a pass
    return;
  }
  const added = diff.split("\n").filter((l) => l.startsWith("+") && !l.startsWith("+++") && l.includes("!important"));
  assert.deepEqual(added, []);
});
