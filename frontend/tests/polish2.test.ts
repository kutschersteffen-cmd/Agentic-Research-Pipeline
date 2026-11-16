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
