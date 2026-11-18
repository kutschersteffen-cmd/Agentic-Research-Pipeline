import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// Start page simplified (docs/superpowers/specs/2026-11-15-start-page-simplified-design.md).
const css = readFileSync(new URL("../src/index.css", import.meta.url), "utf8");
// Every top-level body of `sel { … }` (selector matched exactly at a line start).
const bodies = (src: string, sel: string) => {
  const out: string[] = [];
  const esc = sel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  for (const m of src.matchAll(new RegExp(`(?:^|\\n|\\s)${esc} \\{([^}]*)\\}`, "g"))) out.push(m[1]);
  assert.ok(out.length, `${sel} rule missing`);
  return out.join(";");
};
// Every `@media (q) { … }` block, joined: the hub rules sit in their own block, not necessarily the last one.
const media = (q: string) => {
  const out: string[] = [];
  for (let i = css.indexOf(`@media (${q}) {`); i >= 0; i = css.indexOf(`@media (${q}) {`, i + 1)) {
    let depth = 0;
    for (let j = css.indexOf("{", i); j < css.length; j++) {
      if (css[j] === "{") depth++;
      else if (css[j] === "}" && --depth === 0) { out.push(css.slice(i, j)); break; }
    }
  }
  assert.ok(out.length, q);
  return out.join("\n");
};

test("sp_ac10_grid", () => {
  const g = bodies(css, ".hub-cards");
  assert.match(g, /grid-template-columns:\s*repeat\(6, minmax\(0, 1fr\)\)/);
  assert.match(g, /gap:\s*20px/);
  assert.match(bodies(css, ".hub-card"), /grid-column:\s*span 2/);
  assert.match(bodies(css, ".hub-card:nth-child(n+4)"), /grid-column:\s*span 3/);
  assert.match(media("max-width: 1100px"), /\.hub-card, \.hub-card:nth-child\(n\+4\) \{ grid-column: span 3; \}/);
  assert.match(media("max-width: 760px"), /\.hub-cards \{ grid-template-columns: minmax\(0, 1fr\); \}[\s\S]*\.hub-card, \.hub-card:nth-child\(n\+4\) \{ grid-column: auto; \}/);
});
test("sp_tablet_last_card_fills_its_row", () => {
  // 761–1100px: five cards at half width leave an empty cell beside Data Hub, so the fifth spans the row.
  assert.match(media("max-width: 1100px"), /\.hub-card:nth-child\(5\) \{ grid-column: 1 \/ -1; \}/);
  // On a phone the single column wins again.
  assert.match(media("max-width: 760px"), /\.hub-card, \.hub-card:nth-child\(n\+4\) \{ grid-column: auto; \}/);
});
test("sp_ac12c_status_word_colours", () => {
  const want: Record<string, string> = { wait: "var(--hi-ink)", now: "var(--run)", failed: "var(--low)", done: "var(--muted)", idle: "var(--muted)", unknown: "var(--muted)" };
  for (const [tone, c] of Object.entries(want)) assert.ok(bodies(css, `.hub-status-${tone}`).includes(`color: ${c}`), tone);
});
test("sp_ac12d_marks", () => {
  const m = bodies(css, ".hub-mark");
  assert.match(m, /width:\s*8px/); assert.match(m, /height:\s*8px/); assert.doesNotMatch(m, /border-radius:\s*(?!0)/);
  const fills: Record<string, string> = { done: "var(--text)", now: "var(--run)", wait: "var(--hi)", failed: "var(--low)" };
  for (const [s, c] of Object.entries(fills)) assert.ok(bodies(css, `.hub-mark-${s}`).includes(`background: ${c}`), s);
  assert.match(bodies(css, ".hub-mark-idle"), /box-shadow:\s*inset 0 0 0 1px var\(--muted\)/);
  assert.match(bodies(css, ".hub-mark-unknown"), /outline:\s*1px dashed var\(--muted\)/);
});
test("sp_ac12e_running_is_never_amber", () => {
  for (const m of css.matchAll(/(^|\n)([^{}\n]*-now[^{}\n]*)\{([^}]*)\}/g)) {
    const sel = m[2].trim();
    if (!/^(\.hub-status-now|\.hub-mark-now|\.ws-accent-now|\.hub-card)/.test(sel)) continue;
    assert.doesNotMatch(m[3], /var\(--hi|var\(--await/, sel);
  }
  assert.match(bodies(css, ".hub-mark-now"), /var\(--run\)/);
  assert.match(bodies(css, ".ws-accent-now"), /var\(--run\)/);
});
test("sp_ac13c_drawing_look", () => {
  assert.match(bodies(css, ".ws-drawing path"), /stroke-width:\s*1px/);
  assert.match(bodies(css, ".ws-face"), /fill:\s*var\(--panel\)/);
  const stroke = bodies(css, ".ws-drawing path").match(/stroke:\s*color-mix\(in srgb, var\(--text\) (\d+)%, transparent\)/);
  assert.ok(stroke && +stroke[1] >= 20 && +stroke[1] <= 30, "stroke mix 20–30%");
});

// UI polish 1, F7: the failed tile uses the failed colour, never amber.
test("pol_ac7b_failed_tile_css", () => {
  const r = bodies(css, ".argus-tile-failed");
  assert.match(r, /var\(--low\)/);
  assert.doesNotMatch(r, /var\(--(hi|hi-ink|await|await-edge)\)/);
});

test("pol_ac6c_no_hidden_hub_h1", () => {
  assert.doesNotMatch(css, /\.hub-nav\s*~\s*\.page\s*>\s*h1/);
});
