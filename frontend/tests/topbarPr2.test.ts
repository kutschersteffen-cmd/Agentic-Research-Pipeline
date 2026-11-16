import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// App-wide top bar, PR 2 (docs/superpowers/specs/2026-11-15-app-wide-top-bar-design.md, AC-25..AC-31).
const css = readFileSync(new URL("../src/index.css", import.meta.url), "utf8");
const rule = (sel: string) => {
  const i = css.indexOf(`${sel} {`);
  assert.ok(i >= 0, `${sel} rule missing`);
  return css.slice(i, css.indexOf("}", i));
};

test("pr2_ac26_css", () => {
  assert.doesNotMatch(css, /hub-dot/);
  const st = rule(".hub-step-status::before");
  assert.match(st, /width: 8px/);
  assert.match(st, /height: 8px/);
  assert.doesNotMatch(st, /border-radius: (?!0[;\s])/);
  assert.match(rule(".hub-step:hover"), /border-color: var\(--text\)/);
});

test("pr2_ac27_status_pill", () => {
  const pill = rule(".status-pill");
  assert.doesNotMatch(pill, /border:\s*(?!0|none)/);
  assert.doesNotMatch(pill, /border-radius:\s*(?!0[;\s])/);
  const sq = rule(".status-pill::before");
  assert.match(sq, /width: 8px/);
  assert.match(sq, /height: 8px/);
  assert.match(sq, /background: currentColor/);
  assert.match(rule(".status-running"), /color: var\(--run\)/);
});
test("pr2_ac29_channel_chip", () => {
  const src = readFileSync(new URL("../src/pages/ThemeResearch.tsx", import.meta.url), "utf8");
  const line = src.split("\n").find((l) => l.includes("item.channel &&")) ?? "";
  assert.match(line, /className="chip"/);
  assert.doesNotMatch(line, /status-pill/);
});
