import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { askBox, cardView, runningDetail, stepCount, stepRail, workspaceCaption } from "../src/lib/workspaceCard.ts";
import { WORKSPACES } from "../src/lib/processes.ts";
import type { RunManifest } from "../src/types.ts";

// Expressive UI Orb, slice 3: inside a workspace and the Agent screen (docs/superpowers/specs/2026-11-22-expressive-ui-orb.md).
const src = (f: string) => readFileSync(new URL(`../src/${f}`, import.meta.url), "utf8");
const css = src("index.css");
const hub = src("pages/ProcessHub.tsx");
const agent = src("pages/Agent.tsx");
const T = "2026-11-22T10:00:00Z";
const run = (run_id: string, run_type: string, status: string, extra: Partial<RunManifest> = {}) =>
  ({ run_id, run_type, status, review_count: 0, company_count: 5, completed_count: 5, failed_count: 0, created_at: T, updated_at: T, ...extra }) as unknown as RunManifest;
const R1 = [run("r1", "emerging_themes", "running", { company_count: 480, completed_count: 212 })];
const R2 = [run("r2", "theme", "completed", { review_count: 2 })];
const ws = (id: string) => WORKSPACES.find((w) => w.id === id)!;
const thematic = ws("rdLab").processes.find((p) => p.id === "thematic")!;

test("eo_ac46_caption", () => {
  assert.equal(workspaceCaption(ws("rdLab")), "Workspace · 4 processes");
  assert.equal(workspaceCaption(ws("dataHub")), "Workspace · 1 process");
});

test("eo_ac48_status_line", () => {
  const v = cardView(ws("rdLab"), R1, null, new Date(T));
  assert.equal(v.status.word, "Running");
  assert.equal(runningDetail(ws("rdLab"), R1, null, true), "Build a thematic portfolio · Spot · step 1 of 7");
  assert.equal(runningDetail(ws("rdLab"), R1, null), "Spot · step 1 of 7"); // the start card keeps its detail
  assert.match(hub, /data-ws-status/);
});

test("eo_ac49_51_step_rail", () => {
  assert.deepEqual(stepRail(thematic, R1, null), ["now", "idle", "idle", "idle", "idle", "idle", "idle"]);
  assert.deepEqual(stepRail(thematic, R2, null), ["idle", "idle", "done", "wait", "idle", "idle", "idle"]);
  assert.deepEqual(stepRail(thematic, null, null), Array(7).fill("unknown"));
  const planned = { ...thematic, steps: [...thematic.steps.slice(0, 1), { ...thematic.steps[1], planned: true }] };
  assert.deepEqual(stepRail(planned, null, null), ["unknown", "planned"]);
  assert.deepEqual(stepRail(planned, R1, null), ["now", "planned"]);
});

test("eo_ac50_step_count", () => {
  const spot = thematic.steps[0];
  assert.equal(stepCount(spot, R1), "212 of 480");
  assert.equal(stepCount(spot, null), null);
  assert.equal(stepCount(spot, [run("r1", "emerging_themes", "running", { company_count: 0, completed_count: 0 })]), null);
  assert.equal(stepCount(spot, [run("r9", "emerging_themes", "completed", { company_count: 9, completed_count: 9 })]), null);
  // The most recently updated running or pending run counts.
  const newer = run("r1b", "emerging_themes", "pending", { company_count: 10, completed_count: 3, updated_at: "2026-11-22T11:00:00Z" });
  assert.equal(stepCount(spot, [...R1, newer]), "3 of 10");
});

test("eo_ac54_55_ask_box", () => {
  assert.deepEqual(askBox(ws("rdLab"), true), { label: "Ask about R&D Lab" });
  assert.deepEqual(askBox(ws("transitionIntel"), true), { label: "Ask about Transition Intel" });
  assert.equal(askBox(ws("rdLab"), false), null);
  // Without the ask handler (canAsk false) the overview renders neither the region nor its Orb.
  assert.match(hub, /const ask = askBox\(w, onAsk !== undefined\);/);
  assert.match(hub, /\{ask && <WorkspaceAsk /);
  assert.equal(hub.match(/<Orb place="workspace"/g)?.length, 1);
  assert.match(hub, /<aside className="hub-ask" aria-label="Ask ARP">[\s\S]*<Orb place="workspace" label \/>/);
});

test("eo_ac56_sends_trimmed", () => {
  assert.match(hub, /const q = text\.trim\(\);\s*if \(q\) onAsk\(q\);/);
  assert.match(src("App.tsx"), /<WorkspaceOverview key=\{active\} id=\{active\} onAsk=\{canAsk \? askAgent : undefined\} \/>/);
});

test("eo_ac57_58_agent_orb", () => {
  assert.match(agent, /<div className="agent-head">\s*<Orb place="agent" working=\{asking !== null\} \/>\s*<h1>Agent<\/h1>/);
  assert.match(css, /\.agent-head > \.orb \{ flex: none; width: 56px; height: 56px; \}/);
});

test("eo_ac47_pixel_titles", () => {
  assert.match(css, /\.page\.hub-ws > h1 \{[^}]*font-family: var\(--font-pixel\); font-weight: 400; font-size: clamp\(48px, 6\.4vw, 92px\); line-height: 0\.94;/);
  assert.match(css, /\.argus-head h1 \{ font-family: var\(--font-pixel\); font-weight: 400;/);
});

test("eo_panels_and_figure", () => {
  assert.match(hub, /<section className="hub-process" data-state=\{state \?\? "unknown"\}/);
  assert.match(css, /\.hub-process\[data-state="now"\] \{ box-shadow: 0 0 44px -18px var\(--run\); \}/);
  assert.match(css, /\.hub-process\[data-state="wait"\] \{ border-color: var\(--await-edge\);/);
  assert.match(css, /\.hub-ws-fig \{[^}]*height: 240px;/);
  assert.match(css, /@media \(max-width: 760px\) \{[^@]*\.hub-ws-fig \{[^}]*height: 200px;/);
  assert.match(css, /\.hub-rail \[data-seg="planned"\] \{[^}]*dashed/);
});
