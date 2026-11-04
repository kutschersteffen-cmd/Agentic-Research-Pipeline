import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { cardView } from "../src/lib/workspaceCard.ts";
import { WORKSPACES } from "../src/lib/processes.ts";
import type { RunManifest, StewardshipFlow } from "../src/types.ts";

// Fixtures from docs/superpowers/specs/2026-11-03-start-page-cards-as-navigation-design.md (Acceptance).
const NOW = new Date("2026-11-03T12:00:00Z");
const TWO_H_AGO = new Date(NOW.getTime() - 2 * 3600 * 1000).toISOString();
const run = (run_type: string, status: string, review_count = 0) =>
  ({ run_id: `${run_type}-1`, run_type, status, review_count, updated_at: TWO_H_AGO, company_count: 0, completed_count: 0 }) as unknown as RunManifest;
const flowWith = (open: Record<string, number>) =>
  ({ stages: Object.entries(open).map(([id, n]) => ({ id, decisions: Array.from({ length: n }, () => ({ kind: "outreach", decision: null })) })) }) as unknown as StewardshipFlow;

const busy = {
  runs: [run("extraction", "completed", 7), run("theme", "failed"), run("transition_plan", "running"), run("proxy_voting", "completed", 3)],
  flow: flowWith({ drafting: 2 }),
};
const calm = { runs: [run("extraction", "completed")], flow: flowWith({}) };
const ws = (name: string) => WORKSPACES.find((w) => w.name === name)!;
const view = (name: string, s: { runs: RunManifest[] | null; flow: StewardshipFlow | null }) => cardView(ws(name), s.runs, s.flow, NOW);
const down = { runs: null, flow: null };

test("AC-1/2/3: every card's footer is 'Open →' in busy, calm and down", () => {
  for (const s of [busy, calm, down]) for (const w of WORKSPACES) assert.equal(cardView(w, s.runs, s.flow, NOW).footer, "Open →", w.name);
});

test("AC-4: busy R&D Lab first dot is failed", () => assert.equal(view("R&D Lab", busy).dots[0], "failed"));
test("AC-5: busy Argus first dot is wait", () => assert.equal(view("Argus", busy).dots[0], "wait"));
test("AC-6: busy StewardIQ first two dots wait", () => assert.deepEqual(view("StewardIQ", busy).dots.slice(0, 2), ["wait", "wait"]));
test("AC-7: busy Transition Intelligence Platform has a running dot", () => assert.ok(view("Transition Intelligence Platform", busy).dots.includes("now")));
test("AC-8: busy Data Hub dots are idle", () => assert.deepEqual(view("Data Hub", busy).dots, ["idle"]));

test("AC-9: awaits only where a dot waits", () => {
  const got = Object.fromEntries(WORKSPACES.map((w) => [w.name, cardView(w, busy.runs, busy.flow, NOW).awaits]));
  assert.deepEqual(got, { StewardIQ: true, Argus: true, "Transition Intelligence Platform": false, "R&D Lab": false, "Data Hub": false });
});

test("AC-10: busy R&D Lab now line names the failed process", () => assert.equal(view("R&D Lab", busy).now, "Launch a thematic product"));
test("AC-11: busy Data Hub now line", () => assert.equal(view("Data Hub", busy).now, "No runs yet"));
test("AC-12: calm Argus now line gives the last run's age", () => assert.equal(view("Argus", calm).now, "Last run 2 h ago"));

test("AC-13: down cards have an empty now line and unknown dots", () => {
  for (const w of WORKSPACES) {
    const v = cardView(w, null, null, NOW);
    assert.equal(v.now, "", w.name);
    assert.ok(v.dots.every((d) => d === "unknown"), w.name);
  }
});

test("AC-14: busy Argus label lists process states, no count", () =>
  assert.equal(view("Argus", busy).label, "Argus. Extract and score: waiting on a person; XBRL facts: no activity yet"));
test("AC-21: down Argus label", () =>
  assert.equal(view("Argus", down).label, "Argus. Extract and score: status unknown; XBRL facts: status unknown"));

test("AC-20: DESIGN.md no longer promises a status line on the card", () => {
  const design = readFileSync(new URL("../../DESIGN.md", import.meta.url), "utf8");
  assert.ok(!design.includes("a status in the signal colour when someone is needed"));
});
