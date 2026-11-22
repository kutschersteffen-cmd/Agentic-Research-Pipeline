import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { cardStatus, cardView, failedProcesses, alsoWaiting, waitingBadge, stepStatusLine, workspaceMenuItems, workspaceState } from "../src/lib/workspaceCard.ts";
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

// Start page simplified (2026-11-15) retired AC-1/2/3 (card footer "Open →").

test("AC-4: busy R&D Lab first dot is failed", () => assert.equal(view("R&D Lab", busy).dots[0], "failed"));
test("AC-5: busy Argus first dot is wait", () => assert.equal(view("Argus", busy).dots[0], "wait"));
test("AC-6: busy StewardIQ first two dots wait", () => assert.deepEqual(view("StewardIQ", busy).dots.slice(0, 2), ["wait", "wait"]));
test("AC-7: busy Transition Intelligence Platform has a running dot", () => assert.ok(view("Transition Intelligence Platform", busy).dots.includes("now")));
test("AC-8: busy Data Hub dots are idle", () => assert.deepEqual(view("Data Hub", busy).dots, ["idle"]));

test("AC-9: awaits only where a dot waits", () => {
  const got = Object.fromEntries(WORKSPACES.map((w) => [w.name, cardView(w, busy.runs, busy.flow, NOW).awaits]));
  assert.deepEqual(got, { StewardIQ: true, Argus: true, "Transition Intelligence Platform": false, "R&D Lab": false, "Data Hub": false });
});

test("AC-10: busy R&D Lab now line names the failed process", () => assert.equal(view("R&D Lab", busy).now, "Build a thematic portfolio"));
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
  // Walk up to the repo root: Stryker runs this file from a sandbox copy one or two folders deeper.
  const up = ["../../", "../../../", "../../../../"].map((p) => new URL(`${p}DESIGN.md`, import.meta.url));
  const design = readFileSync(up.find((u) => existsSync(u)) ?? up[0], "utf8");
  assert.ok(!design.includes("a status in the signal colour when someone is needed"));
});

// Night Desk release 2 (docs/superpowers/specs/2026-11-08-night-desk-status-design.md).
const D = "2026-11-08T10:00:00Z";
test("r2 AC-3: 3 waiting", () => assert.deepEqual(stepStatusLine("wait", 3, 0, null), { text: "3 waiting on you", tone: "wait" }));
test("r2 AC-4: 1 waiting wins over idle", () => assert.deepEqual(stepStatusLine("idle", 1, 0, null), { text: "1 waiting on you", tone: "wait" }));
test("r2: waiting wins over failed", () => assert.deepEqual(stepStatusLine("failed", 2, 0, null), { text: "2 waiting on you", tone: "wait" }));
test("r2 AC-5: 2 decisions open", () => assert.deepEqual(stepStatusLine("done", 0, 2, null), { text: "2 decisions open", tone: "wait" }));
test("r2 AC-6: 1 decision open", () => assert.deepEqual(stepStatusLine("done", 0, 1, null), { text: "1 decision open", tone: "wait" }));
test("r2 AC-7: running", () => assert.deepEqual(stepStatusLine("now", 0, 0, null), { text: "Running", tone: "now" }));
test("r2 AC-8: failed", () => assert.deepEqual(stepStatusLine("failed", 0, 0, D), { text: "Last run failed", tone: "failed" }));
test("r2 AC-9: done with date", () => assert.deepEqual(stepStatusLine("done", 0, 0, D, "en-GB"), { text: "Done · 8 Nov", tone: "done" }));
test("r2 AC-10: idle", () => assert.deepEqual(stepStatusLine("idle", 0, 0, null), { text: "No runs yet", tone: "idle" }));
test("r2 AC-11: a waiting process makes the workspace wait", () => assert.equal(workspaceState(ws("Argus"), busy.runs), "wait"));
test("r2 AC-12: failed outranks done and idle", () => assert.equal(workspaceState(ws("R&D Lab"), busy.runs), "failed"));
test("r2: no runs for the workspace is idle", () => assert.equal(workspaceState(ws("Data Hub"), busy.runs), "idle"));
test("r2 AC-13: runs not loaded is idle", () => assert.equal(workspaceState(ws("Argus"), null), "idle"));
test("r2 AC-19b: workspace order unchanged", () =>
  assert.deepEqual(WORKSPACES.map((w) => w.name), ["StewardIQ", "Argus", "Transition Intelligence Platform", "R&D Lab", "Data Hub"]));

// Night Desk release 4 and 6 (waiting sentence, link, stat and target) were retired by the
// simplified start page (docs/superpowers/specs/2026-11-15-start-page-simplified-design.md, Supersedes).

// Start page simplified (docs/superpowers/specs/2026-11-15-start-page-simplified-design.md).
const W = (review: number, decisions: number, ballots: number, total = review + decisions + ballots) => ({ review, decisions, ballots, total });
test("wc_ac5_waiting_badge", () => {
  assert.deepEqual(waitingBadge(W(82, 15, 3)), {
    text: "100",
    title: "100 waiting for a decision: 82 review items, 15 stewardship decisions, 3 ballots",
  });
});
test("wc_ac6_singulars_and_zero", () => {
  assert.deepEqual(waitingBadge(W(1, 0, 0)), { text: "1", title: "1 waiting for a decision: 1 review item" });
  assert.deepEqual(waitingBadge(W(0, 1, 0)), { text: "1", title: "1 waiting for a decision: 1 stewardship decision" });
  assert.deepEqual(waitingBadge(W(0, 0, 1)), { text: "1", title: "1 waiting for a decision: 1 ballot" });
  assert.equal(waitingBadge(W(0, 0, 0)), null);
});
test("wc_waiting_badge_rejects_bad_input", () => {
  assert.equal(waitingBadge(W(-1, 2, 0, 1)), null);
  assert.equal(waitingBadge(W(1, 0, 0, NaN)), null);
  assert.equal(waitingBadge(W(1.5, 0, 0, 1.5)), null);
  assert.equal(waitingBadge(W(1, 1, 0, 3)), null); // total is not the sum
});
test("wc_also_waiting", () => {
  assert.deepEqual(alsoWaiting(W(0, 15, 3)), [
    { text: "15 stewardship decisions also wait, in Steward Workflow →", href: "#/stewardship" },
    { text: "3 ballots also wait, in Proxy Voting →", href: "#/voting" },
  ]);
  assert.deepEqual(alsoWaiting(W(1, 1, 0)), [{ text: "1 stewardship decision also waits, in Steward Workflow →", href: "#/stewardship" }]);
  assert.deepEqual(alsoWaiting(W(0, 0, 1)), [{ text: "1 ballot also waits, in Proxy Voting →", href: "#/voting" }]);
  assert.deepEqual(alsoWaiting(W(5, 0, 0)), []);
});
const T = ["Engage", "Vote", "Track"];
const CASES: [Parameters<typeof cardStatus>[0], string, [string, string, string]][] = [
  [["done", "wait", "idle"], "", ["Waiting on you", "wait", "Vote"]],
  [["now", "idle"], "", ["Running", "now", "Engage"]],
  [["failed", "done"], "", ["Last run failed", "failed", "Engage"]],
  [["done", "done"], "Last run 2 h ago", ["Up to date", "done", "Last run 2 h ago"]],
  [["idle"], "No runs yet", ["No runs yet", "idle", ""]],
  [null, "", ["Status unknown", "unknown", ""]],
];
test("sp_ac12_card_status", () => {
  for (const [states, last, [word, tone, detail]] of CASES) assert.deepEqual(cardStatus(states, T, last), { word, tone, detail }, String(states));
});
test("sp_ac12b_detail_never_repeats_word", () => {
  for (const [states, last] of CASES) { const r = cardStatus(states, T, last); assert.notEqual(r.detail, r.word); }
});
test("sp_review_up_to_date_names_when_any_step_ran", () => {
  // A finished Identify run (not in Argus's own runTypes) still dates the card: never "Up to date · No runs yet".
  const s = view("Argus", { runs: [run("identity", "completed")], flow: flowWith({}) }).status;
  assert.equal(s.word, "Up to date");
  assert.equal(s.detail, "Last run 2 h ago");
});
test("sp_ac19_card_status_in_view", () => {
  assert.equal(view("Argus", busy).status.word, "Waiting on you");
  assert.equal(view("Argus", down).status.word, "Status unknown");
});

// App-wide top bar, PR 1: the Workspaces menu.
test("pr1_menu_items", () => {
  const empty = workspaceMenuItems(null, null, NOW);
  assert.deepEqual(empty.map((i) => i.label), ["Start", "StewardIQ", "Argus", "Transition Intel", "R&D Lab", "Data Hub"]);
  assert.deepEqual(empty.map((i) => i.href), ["#/home", "#/stewardiq", "#/argus", "#/transitionIntel", "#/rdLab", "#/dataHub"]);
  assert.ok(empty.every((i) => i.tone === null && i.word === ""));
  const steward = workspaceMenuItems(busy.runs, busy.flow, NOW).find((i) => i.label === "StewardIQ")!;
  assert.deepEqual([steward.tone, steward.word], ["wait", "Waiting on you"]);
});

// UI polish 1, F9: each workspace's purpose under its name in the Workspaces menu.
test("pol_menu_purpose", () => {
  const items = workspaceMenuItems(null, null, NOW);
  assert.equal(items[0].purpose, "Every workspace at a glance");
  assert.deepEqual(items.slice(1).map((i) => i.purpose), WORKSPACES.map((w) => w.purpose));
});

// UI polish 1, F11: titles of a workspace's failed processes.
test("pol_ac11_failed_processes", () => {
  const lab = ws("R&D Lab");
  const watching = lab.processes.filter((p) => p.steps.some((s) => s.runTypes?.includes("calibration"))).map((p) => p.title);
  assert.ok(watching.length >= 1);
  assert.deepEqual(failedProcesses(lab, [run("calibration", "failed")], null, null), watching);
  assert.deepEqual(failedProcesses(lab, [run("emerging_themes", "failed")], null, null), ["Build a thematic portfolio"]);
  assert.deepEqual(failedProcesses(lab, [], null, null), []);
  assert.deepEqual(failedProcesses(lab, null, null, null), []);
});
test("pol_failed_with_wait", () => {
  // StewardIQ waits on open decisions while a proxy-voting run failed: the failed line still names it.
  const sq = ws("StewardIQ");
  const out = failedProcesses(sq, [run("proxy_voting", "failed")], flowWith({ drafting: 2 }), null);
  const voting = sq.processes.filter((p) => p.steps.some((s) => s.runTypes?.includes("proxy_voting"))).map((p) => p.title);
  assert.deepEqual(out, voting);
  assert.deepEqual(voting, ["Proxy season"]);
});

test("rd-lab-rename AC-11: Argus Template step names R&D Lab", () => {
  const steps = WORKSPACES.find((w) => w.id === "argus")!.processes.flatMap((p) => p.steps);
  assert.equal(steps.find((s) => s.label === "Template")!.does, "Build and ratify scoring templates in Decision Studio (R&D Lab); only ratified versions reach Argus.");
});
