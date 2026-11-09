import type { RunManifest, StewardshipFlow, StewardshipStage } from "../types";
import type { Process, Step, Workspace } from "./processes.ts";
import { ACTIVE_STATUSES, ago, decisionRunType, waitingCount } from "./runs.ts";

/** Decisions a stage still waits on: every item except policy differences
 * already decided. */
export const openCount = (stage: StewardshipStage | undefined) =>
  stage ? stage.decisions.filter((d) => d.kind !== "policy_difference" || d.decision === null).length : 0;

export type StepState = "done" | "now" | "wait" | "failed" | "idle";
export const DONE = new Set(["completed", "partially_completed"]);
export const STATE_LABEL: Record<StepState, string> = { done: "has a finished run", now: "running", wait: "waiting on a person", failed: "last run failed", idle: "no activity yet" };

export function stepState(step: Step, runs: RunManifest[] | null, flow: StewardshipFlow | null): StepState {
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
  return "idle";
}

const RANK: StepState[] = ["wait", "now", "failed", "done", "idle"];
/** A process's one state: the most urgent of its steps'. */
export const processState = (p: Process, runs: RunManifest[] | null, flow: StewardshipFlow | null): StepState => {
  const states = p.steps.map((s) => stepState(s, runs, flow));
  return RANK.find((r) => states.includes(r)) ?? "idle";
};

export type CardView = { dots: (StepState | "unknown")[]; now: string; footer: string; label: string; awaits: boolean };

/** What a start-page workspace card shows. The card is a way in, not a status: waiting work is
 * counted once, in the start page headline, so the card carries no counts. */
export function cardView(w: Workspace, runs: RunManifest[] | null, flow: StewardshipFlow | null, now: Date): CardView {
  const footer = "Open →";
  // Before runs load (or when the backend is down) every state is unknown, not idle.
  if (!runs) {
    return { dots: w.processes.map(() => "unknown"), now: "", footer, awaits: false, label: `${w.name}. ${w.processes.map((p) => `${p.title}: status unknown`).join("; ")}` };
  }
  const dots = w.processes.map((p) => processState(p, runs, flow));
  // The process named is the one a person should look at: a wait first, then running or failed.
  const firstWait = dots.indexOf("wait");
  const at = firstWait >= 0 ? firstWait : dots.findIndex((st) => st === "now" || st === "failed");
  const last = runs.filter((r) => w.runTypes.includes(r.run_type)).sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))[0];
  const line = at >= 0 ? w.processes[at].title : last ? `Last run ${ago(last.updated_at, now)}` : "No runs yet";
  // The link's label replaces its inner text for screen readers, so it carries each process's state.
  const label = `${w.name}. ${w.processes.map((p, i) => `${p.title}: ${STATE_LABEL[dots[i]]}`).join("; ")}`;
  return { dots, now: line, footer, label, awaits: firstWait >= 0 };
}

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

type WaitingTotal = number | "error" | null;
/** The start page's one line on what waits on a person, for every loading and error state. */
export const waitingSentence = (known: boolean, error: string | null, needsTotal: WaitingTotal): string =>
  !known ? (error ? "Runs could not be loaded." : "Loading runs…") : needsTotal === "error" ? "What waits on you could not be loaded." : needsTotal === null ? "Loading what waits on you…" : needsTotal > 0 ? needsTotal === 1 ? "1 decision waits on you." : `${needsTotal} decisions wait on you.` : "Nothing waits on you.";

/** The same line as a link to the Review Queue when something waits; plain text otherwise. */
export function waitingLink(known: boolean, error: string | null, needsTotal: WaitingTotal): { text: string; href: "#/review" | null } {
  const text = waitingSentence(known, error, needsTotal);
  return known && typeof needsTotal === "number" && needsTotal > 0 ? { text: `${text.replace(/\.$/, "")} →`, href: "#/review" } : { text, href: null };
}

/** The waiting count for the start page's counts: the number, or a dash while unknown. */
export const waitingStat = (needsTotal: WaitingTotal): string => (typeof needsTotal === "number" && Number.isFinite(needsTotal) ? String(needsTotal) : "—");
