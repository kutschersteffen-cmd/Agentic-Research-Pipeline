import type { RunManifest, StewardshipFlow, StewardshipStage } from "../types";
import { WORKSPACES, type Process, type Step, type Workspace } from "./processes.ts";
import { ACTIVE_STATUSES, ago, decisionRunType, waitingCount } from "./runs.ts";

/** Decisions a stage still waits on: every item except policy differences
 * already decided. */
export const openCount = (stage: StewardshipStage | undefined) =>
  stage ? stage.decisions.filter((d) => d.kind !== "policy_difference" || d.decision === null).length : 0;

export type StepState = "done" | "now" | "wait" | "failed" | "idle";
export const DONE = new Set(["completed", "partially_completed"]);
export const STATE_LABEL: Record<StepState, string> = { done: "has a finished run", now: "running", wait: "waiting on a person", failed: "last run failed", idle: "no activity yet" };

/** What the hub reads besides runs: the feed overview (`GET /api/feeds`) and the last monthly run that ran. */
export type Activity = {
  feeds: { feed: string; last_load: { status: string; at: string } | null }[];
  lastRun: { at: string } | null;
};

/** The state of a step whose work leaves no run: a load (security master, holdings) or the monthly run. Null for
 * every other step, and for these when no activity was passed. `at` is when it was last done. */
export function stepActivity(step: Step, activity?: Activity | null): { state: StepState; at: string | null } | null {
  if (!activity) return null;
  const fromLoads = (feeds: string[]) => {
    const loads = activity.feeds.filter((f) => feeds.includes(f.feed) && f.last_load).map((f) => f.last_load!);
    const ok = loads.filter((l) => l.status === "ok").map((l) => l.at).sort();
    if (ok.length) return { state: "done" as const, at: ok[ok.length - 1] };
    return { state: loads.some((l) => l.status === "failed") ? ("failed" as const) : ("idle" as const), at: null };
  };
  if (step.tab === "securityMaster" && step.label === "Load security master") return fromLoads(["security_master"]);
  if (step.tab === "portfolio-monitoring" && step.sub === "holdings") return fromLoads(["holdings", "index"]);
  if (step.tab === "portfolio-monitoring" && step.sub === "monitoring") {
    return activity.lastRun ? { state: "done", at: activity.lastRun.at } : { state: "idle", at: null };
  }
  return null;
}

export function stepState(step: Step, runs: RunManifest[] | null, flow: StewardshipFlow | null, activity?: Activity | null): StepState {
  if (step.runTypes && runs) {
    const mine = runs.filter((r) => step.runTypes!.includes(decisionRunType(r)));
    // Waiting on a person outranks running: that is what the signal colour is for.
    if (!step.reviewedElsewhere && mine.some((r) => waitingCount(r) > 0)) return "wait";
    if (mine.some((r) => ACTIVE_STATUSES.has(r.status))) return "now";
    const latest = mine.sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))[0];
    if (latest?.status === "failed") return "failed";
    if (mine.some((r) => DONE.has(r.status))) return "done";
  }
  if (step.stage && openCount(flow?.stages.find((s) => s.id === step.stage)) > 0) return "wait";
  return stepActivity(step, activity)?.state ?? "idle";
}

const RANK: StepState[] = ["wait", "now", "failed", "done", "idle"];
/** A process's one state: the most urgent of its steps'. */
export const processState = (p: Process, runs: RunManifest[] | null, flow: StewardshipFlow | null, activity?: Activity | null): StepState => {
  const states = p.steps.map((s) => stepState(s, runs, flow, activity));
  return RANK.find((r) => states.includes(r)) ?? "idle";
};

/** A process's track: `reached` is the last done step (-1 if none); `runInto[i]` marks a running step right after
 * the reached part (or a running first step), whose incoming connector is drawn in the running colour. */
export function flowTrack(states: StepState[]): { reached: number; runInto: boolean[] } {
  const reached = states.lastIndexOf("done");
  return { reached, runInto: states.map((s, i) => s === "now" && i <= reached + 1) };
}

/** Titles of a workspace's processes whose state is failed, for the overview's "Last run failed" lines. */
export const failedProcesses = (w: Workspace, runs: RunManifest[] | null, flow: StewardshipFlow | null, activity: Activity | null): string[] =>
  w.processes.filter((p) => p.steps.some((s) => stepState(s, runs, flow, activity) === "failed")).map((p) => p.title);

export type CardStatus = { word: string; tone: StepState | "unknown"; detail: string };
export type CardView = { dots: (StepState | "unknown")[]; now: string; status: CardStatus; label: string; awaits: boolean };

/** A card's status line: the most urgent state as a word, and the process it concerns. The detail
 * never repeats the word: it names a process, or for finished work when it last ran. */
export function cardStatus(states: (StepState | "unknown")[] | null, titles: string[], lastLine: string): CardStatus {
  if (!states) return { word: "Status unknown", tone: "unknown", detail: "" };
  const named: [StepState, string][] = [["wait", "Waiting on you"], ["now", "Running"], ["failed", "Last run failed"]];
  for (const [tone, word] of named) {
    const i = states.indexOf(tone);
    if (i >= 0) return { word, tone, detail: titles[i] ?? "" };
  }
  if (states.includes("done")) return { word: "Up to date", tone: "done", detail: lastLine };
  return { word: "No runs yet", tone: "idle", detail: "" };
}

type Waiting = { review: number; decisions: number; ballots: number; total: number };
const PARTS = [
  ["review", "review item", "review items"],
  ["decisions", "stewardship decision", "stewardship decisions"],
  ["ballots", "ballot", "ballots"],
] as const;
const counted = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const sane = (w: Waiting) =>
  [w.review, w.decisions, w.ballots, w.total].every((n) => Number.isInteger(n) && n >= 0) && w.total === w.review + w.decisions + w.ballots;

/** The Review Queue badge: everything waiting on a decision, its parts named in the label. Hidden at 0 or on bad input. */
export const waitingBadge = (w: Waiting): { text: string; title: string } | null =>
  sane(w) && w.total > 0
    ? { text: String(w.total), title: `${w.total} waiting for a decision: ${PARTS.filter(([k]) => w[k] > 0).map(([k, one, many]) => counted(w[k], one, many)).join(", ")}` }
    : null;

/** The Review Queue's note on what waits elsewhere: stewardship decisions and ballots. */
export const alsoWaiting = (w: Waiting): { text: string; href: string }[] =>
  sane(w)
    ? [
        { n: w.decisions, one: "stewardship decision", many: "stewardship decisions", place: "Steward Workflow", href: "#/stewardship" },
        { n: w.ballots, one: "ballot", many: "ballots", place: "Proxy Voting", href: "#/voting" },
      ]
        .filter((p) => p.n > 0)
        .map((p) => ({ text: `${counted(p.n, p.one, p.many)} also ${p.n === 1 ? "waits" : "wait"}, in ${p.place} →`, href: p.href }))
    : [];

/** What a start-page workspace card shows: the way in, each process's state, and one status line. */
export function cardView(w: Workspace, runs: RunManifest[] | null, flow: StewardshipFlow | null, now: Date): CardView {
  // Before runs load (or when the backend is down) every state is unknown, not idle.
  if (!runs) {
    return { dots: w.processes.map(() => "unknown"), now: "", status: cardStatus(null, [], ""), awaits: false, label: `${w.name}. ${w.processes.map((p) => `${p.title}: status unknown`).join("; ")}` };
  }
  const dots = w.processes.map((p) => processState(p, runs, flow));
  // The process named is the one a person should look at: a wait first, then running or failed.
  const firstWait = dots.indexOf("wait");
  const at = firstWait >= 0 ? firstWait : dots.findIndex((st) => st === "now" || st === "failed");
  // Any run behind any step dates the card, so "Up to date" never sits beside "No runs yet".
  const types = new Set([...w.runTypes, ...w.processes.flatMap((p) => p.steps.flatMap((s) => s.runTypes ?? []))]);
  const last = runs.filter((r) => types.has(decisionRunType(r))).sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))[0];
  const line = at >= 0 ? w.processes[at].title : last ? `Last run ${ago(last.updated_at, now)}` : "No runs yet";
  // The link's label replaces its inner text for screen readers, so it carries each process's state.
  const label = `${w.name}. ${w.processes.map((p, i) => `${p.title}: ${STATE_LABEL[dots[i]]}`).join("; ")}`;
  const status = cardStatus(dots, w.processes.map((p) => p.title), line);
  return { dots, now: line, status, label, awaits: firstWait >= 0 };
}

/** A running card's detail: "<step> · step i of n" for the first running step of the first running process, led by
 * the process title when `named` (the workspace overview's status line). Null when no process runs. */
export function runningDetail(w: Workspace, runs: RunManifest[] | null, flow: StewardshipFlow | null, named = false): string | null {
  if (!runs) return null;
  const p = w.processes.find((x) => processState(x, runs, flow) === "now");
  const i = p ? p.steps.findIndex((s) => stepState(s, runs, flow) === "now") : -1;
  return p && i >= 0 ? `${named ? `${p.title} · ` : ""}${p.steps[i].label} · step ${i + 1} of ${p.steps.length}` : null;
}

/** The workspace overview's caption: "Workspace · 4 processes". */
export const workspaceCaption = (w: Workspace): string => `Workspace · ${w.processes.length} ${w.processes.length === 1 ? "process" : "processes"}`;

export type StepSeg = StepState | "planned" | "unknown";
/** A process's step rail: one segment per step, in step order. A planned step is `planned`; before the runs have
 * loaded every other step is `unknown`. */
export const stepRail = (p: Process, runs: RunManifest[] | null, flow: StewardshipFlow | null, activity?: Activity | null): StepSeg[] =>
  p.steps.map((s) => (s.planned ? "planned" : runs ? stepState(s, runs, flow, activity) : "unknown"));

/** "c of m" under a running step: `completed_count` of `company_count` of the most recently updated running or pending
 * run among the step's run types. Null without one, or when `m` is 0. */
export function stepCount(step: Step, runs: RunManifest[] | null): string | null {
  if (!step.runTypes || !runs) return null;
  const r = runs
    .filter((x) => ACTIVE_STATUSES.has(x.status) && step.runTypes!.includes(decisionRunType(x)))
    .sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))[0];
  return r && r.company_count > 0 ? `${r.completed_count} of ${r.company_count}` : null;
}

/** The Ask ARP card's question box, only for someone who may ask: its accessible name and placeholder. */
export const askBox = (w: Workspace, canAsk: boolean): { label: string } | null => (canAsk ? { label: `Ask about ${w.short ?? w.name}` } : null);

/** The start page hero's sentence on working agents: a run that is running or pending is an agent at work. */
export function workingSentence(runs: RunManifest[]): string {
  const n = runs.filter((r) => r.status === "running" || r.status === "pending").length;
  return n === 0 ? "No agent is working right now." : n === 1 ? "1 agent is working for you." : `${n} agents are working for you.`;
}

/** The hero's link to "Needs you": absent at 0 or when the count is unknown. */
export const needsYouText = (total: number | null): string | null =>
  total === null || !Number.isInteger(total) || total <= 0 ? null : total === 1 ? "1 item needs you." : `${total} items need you.`;

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** The hero caption, in local time: "Sunday 22 Nov · 22:15". */
export const heroCaption = (d: Date): string =>
  `${WEEKDAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]} · ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;

export type StatusTone = StepState;
/** One line under a step's title: what waits on a person first, then the run state. */
export function stepStatusLine(state: StepState, waiting: number, decisions: number, lastUpdated: string | null, locale?: string): { text: string; tone: StatusTone } {
  if (waiting > 0) return { text: `${waiting} waiting on you`, tone: "wait" };
  if (decisions > 0) return { text: `${decisions} decision${decisions === 1 ? "" : "s"} open`, tone: "wait" };
  if (state === "now") return { text: "Running", tone: "now" };
  if (state === "failed") return { text: "Last run failed", tone: "failed" };
  if (state === "done" && lastUpdated) {
    const d = new Date(lastUpdated).toLocaleDateString(locale, { day: "numeric", month: "short", timeZone: "UTC" });
    return { text: `Done · ${d}`, tone: "done" };
  }
  return { text: "No runs yet", tone: "idle" };
}

/** A workspace's one state for the sidebar dot: the most urgent of its processes'. */
export const workspaceState = (w: Workspace, runs: RunManifest[] | null): StepState => {
  if (!runs) return "idle";
  const states = w.processes.map((p) => processState(p, runs, null));
  return RANK.find((r) => states.includes(r)) ?? "idle";
};

export type MenuItem = { href: string; label: string; purpose: string; tone: "wait" | "now" | "failed" | null; word: string };
/** The top bar's Workspaces menu: Start, then each workspace with its card's status when it needs a look. */
export function workspaceMenuItems(runs: RunManifest[] | null, flow: StewardshipFlow | null, now: Date): MenuItem[] {
  return [
    { href: "#/home", label: "Start", purpose: "Every workspace at a glance", tone: null, word: "" },
    ...WORKSPACES.map((w) => {
      const { tone, word } = cardView(w, runs, flow, now).status;
      const loud = tone === "wait" || tone === "now" || tone === "failed";
      return { href: `#/${w.id}`, label: w.short ?? w.name, purpose: w.purpose, tone: loud ? tone : null, word: loud ? word : "" };
    }),
  ];
}
