import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { cardView, heroCaption, needsYouText, runningDetail, workingSentence } from "../src/lib/workspaceCard.ts";
import { WORKSPACES } from "../src/lib/processes.ts";
import { DRAWING_IDS, drawing } from "../src/lib/workspaceDrawing.ts";
import type { RunManifest } from "../src/types.ts";

// Expressive UI Orb, slice 2: the start page (docs/superpowers/specs/2026-11-22-expressive-ui-orb.md).
const css = readFileSync(new URL("../src/index.css", import.meta.url), "utf8");
const T = "2026-11-22T10:00:00Z";
const run = (run_id: string, run_type: string, status: string, review_count = 0) =>
  ({ run_id, run_type, status, review_count, company_count: 5, completed_count: 5, failed_count: 0, created_at: T, updated_at: T }) as unknown as RunManifest;
const R1 = [run("r1", "emerging_themes", "running")];
const R2 = [run("r2", "theme", "completed", 2)];
const ws = (id: string) => WORKSPACES.find((w) => w.id === id)!;
const NOW = new Date(T);

test("eo_ac33_36_working_sentence", () => {
  assert.equal(workingSentence([]), "No agent is working right now.");
  assert.equal(workingSentence(R1), "1 agent is working for you.");
  assert.equal(workingSentence([...R1, run("r1b", "emerging_themes", "pending")]), "2 agents are working for you.");
  assert.equal(workingSentence([...R2, run("r3", "theme", "failed")]), "No agent is working right now.");
});

test("eo_ac33_36_needs_you", () => {
  assert.equal(needsYouText(null), null);
  assert.equal(needsYouText(0), null);
  assert.equal(needsYouText(1), "1 item needs you.");
  assert.equal(needsYouText(2), "2 items need you.");
});

test("eo_ac38_caption", () => {
  assert.equal(heroCaption(new Date(2026, 10, 22, 22, 15)), "Sunday 22 Nov · 22:15");
  assert.equal(heroCaption(new Date(2026, 0, 5, 7, 3)), "Monday 5 Jan · 07:03");
});

test("eo_ac39_40_running_rd_lab", () => {
  const v = cardView(ws("rdLab"), R1, null, NOW);
  assert.deepEqual(v.dots, ["now", "idle", "idle", "idle"]);
  assert.equal(v.status.word, "Running");
  assert.equal(runningDetail(ws("rdLab"), R1, null), "Spot · step 1 of 7");
  assert.equal(runningDetail(ws("rdLab"), null, null), null);
  assert.equal(runningDetail(ws("argus"), R1, null), null);
});

test("eo_ac41_waiting_argus", () => {
  const v = cardView(ws("argus"), R2, null, NOW);
  assert.deepEqual(v.dots, ["wait", "idle"]);
  assert.equal(v.status.word, "Waiting on you");
});

test("eo_ac85_label_unchanged", () =>
  assert.equal(
    cardView(ws("rdLab"), R1, null, NOW).label,
    "R&D Lab. Build a thematic portfolio: running; Research a theme: no activity yet; Research a strategy: no activity yet; Research a signal: no activity yet",
  ));

test("eo_ac73_one_accent_on_the_top_face", () => {
  for (const id of DRAWING_IDS) {
    for (const acc of ["now", "wait"] as const) {
      const shapes = drawing(id, acc);
      const top = shapes.filter((s) => s.accent);
      assert.equal(top.length, 1, `${id} ${acc}`);
      assert.equal(top[0].part, "top", `${id} ${acc}`);
      assert.ok(shapes.some((s) => s.lit), `${id} ${acc}: side faces move with it`);
    }
    assert.ok(drawing(id, null).every((s) => !s.accent && !s.lit && s.part !== "extra"), id);
  }
});

test("eo_drawing_only_the_status_part_moves", () => {
  // Out vs in: the shapes that change are the status part's (and the extra shown while running), nothing else.
  for (const id of DRAWING_IDS) {
    for (const acc of ["now", "wait"] as const) {
      const out = drawing(id, acc, 1);
      const inn = drawing(id, acc, 0);
      assert.equal(out.length, inn.length, id);
      out.forEach((s, i) => {
        if (s.d !== inn[i].d) assert.ok(s.accent || s.lit || s.part === "extra" || s.part === "detail", `${id} ${acc} shape ${i}`);
      });
      assert.ok(out.some((s, i) => s.accent && s.d !== inn[i].d), `${id} ${acc}: the part is out of place while lit`);
    }
  }
});

test("eo_drawing_extras_while_running", () => {
  assert.equal(drawing("argus", "now").filter((s) => s.part === "extra").length, 1);
  assert.equal(drawing("argus", "wait").filter((s) => s.part === "extra").length, 0);
  assert.equal(drawing("rdLab", "now").filter((s) => s.part === "extra" && s.dash).length, 1);
  // Transition Intel: the 4th fin while running, the 8th while waiting.
  const fin = (acc: "now" | "wait") => drawing("transitionIntel", acc).filter((s) => s.part === "top").findIndex((s) => s.accent);
  assert.equal(fin("now"), 3);
  assert.equal(fin("wait"), 7);
});

test("eo_ac42_44_rail_motion_css", () => {
  const rule = (sel: string) => {
    const i = css.indexOf(`${sel} {`);
    assert.ok(i >= 0, sel);
    return css.slice(i, css.indexOf("}", i));
  };
  assert.match(rule('.hub-rail [data-seg="now"]::before'), /animation:[^;]*infinite/);
  assert.match(rule('.hub-rail [data-seg="wait"]'), /animation:[^;]*infinite/);
  for (const s of ["done", "idle", "unknown", "failed"]) assert.doesNotMatch(rule(`.hub-rail [data-seg="${s}"]`), /animation/, s);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\) \{\n {2}\.hub-rail \[data-seg\], \.hub-rail \[data-seg\]::before, \.hub-rail \[data-seg\]::after \{ animation: none; \}/);
  assert.match(rule('.hub-rail [data-seg="now"]'), /var\(--run\)/);
  assert.doesNotMatch(rule('.hub-rail [data-seg="now"]'), /var\(--hi/);
});

test("eo_ac37_greeting_pixel", () => {
  const i = css.indexOf(".hub-start .hub-hero h1 {");
  const r = css.slice(i, css.indexOf("}", i));
  assert.match(r, /font-family: var\(--font-pixel\)/);
  assert.match(r, /font-weight: 400/);
  assert.match(r, /font-size: clamp\(52px, 7\.2vw, 104px\)/);
});
