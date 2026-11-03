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
 * counted once, in Needs you, so the card carries no counts. */
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
