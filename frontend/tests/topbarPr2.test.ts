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
