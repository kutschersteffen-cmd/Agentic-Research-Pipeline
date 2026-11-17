import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { execSync } from "node:child_process";
import { flowTrack } from "../src/lib/workspaceCard.ts";

// App-wide top bar, PR 3 (docs/superpowers/specs/2026-11-15-app-wide-top-bar-design.md, AC-33..AC-42).

test("pr3_ac39_flow_track", () => {
  assert.deepEqual(flowTrack(["done", "idle", "done", "now", "idle"]), { reached: 2, runInto: [false, false, false, true, false] });
  assert.deepEqual(flowTrack(["now", "idle"]), { reached: -1, runInto: [true, false] });
  assert.deepEqual(flowTrack(["idle", "wait"]), { reached: -1, runInto: [false, false] });
  assert.deepEqual(flowTrack([]), { reached: -1, runInto: [] });
});

const css = readFileSync(new URL("../src/index.css", import.meta.url), "utf8");
const rule = (sel: string) => {
  const i = css.indexOf(`${sel} {`);
  assert.ok(i >= 0, `${sel} rule missing`);
  return css.slice(i, css.indexOf("}", i));
};
const WAIT_LINE = /^\.hub-step-wait, \.hub-step:has\(\.hub-step-banner\).*$/m;

test("pr3_ac38_css", (t) => {
  const now = rule(".hub-step-now, .hub-step-now:hover");
  assert.match(now, /border-color: var\(--run\)/);
  assert.match(now, /box-shadow:[^;]*var\(--run\)/);
  const pulse = rule(".hub-step-now .hub-step-status::before").match(/animation: ([\w-]+) /);
  assert.ok(pulse, "pulse animation missing");
  assert.match(css, new RegExp(`@keyframes ${pulse[1]} \\{`));
  assert.match(css, /@media \(prefers-reduced-motion: reduce\) \{ \.hub-step-now \.hub-step-status::before \{ animation: none; \} \}/);
  const open = rule('.hub-step[aria-expanded="true"]');
  assert.match(open, /outline: 1px solid var\(--text\)/);
  assert.match(open, /outline-offset: 3px/);
  assert.ok(css.indexOf('.hub-step[aria-expanded="true"] {') < css.indexOf(".hub-step:focus-visible {"), "focus outline must win by order");
  let main: string;
  try {
    main = execSync("git show origin/main:frontend/src/index.css", { cwd: new URL("..", import.meta.url), encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
  } catch {
    t.skip("origin/main not fetched"); // reported as skipped, never as a pass
    return;
  }
  assert.equal(css.match(WAIT_LINE)?.[0], main.match(WAIT_LINE)?.[0]);
});

test("pr3_track_css", () => {
  assert.match(rule(".hub-flow-item.reached + .hub-flow-item::before"), /background: var\(--text\)/);
  assert.match(rule(".hub-flow-item + .hub-flow-item.run-into::before"), /background: var\(--run\)/);
  assert.ok(css.indexOf(".hub-flow-item + .hub-flow-item.run-into::before {") > css.indexOf(".hub-flow-item.reached + .hub-flow-item::before {"), "run-into must come later");
  assert.doesNotMatch(css, /hub-step-go/);
});

test("pr3_ac42_copy", () => {
  const src = readFileSync(new URL("../src/pages/ProcessHub.tsx", import.meta.url), "utf8");
  assert.ok(src.includes("Click a step for its details; open it from there."));
  assert.ok(!src.includes("Open a step to work in its screen"));
});

test("pr3_design_md", () => {
  const md = readFileSync(new URL("../../DESIGN.md", import.meta.url), "utf8");
  const entry = md.slice(md.indexOf("**Process flow**"));
  assert.ok(md.includes("**Process flow**"), "entry missing");
  const line = entry.slice(0, entry.indexOf("\n"));
  assert.match(line, /aria-expanded/);
  assert.match(line, /--run/);
});
