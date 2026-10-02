import type { StageState } from "./stagedFlow";
import type { DataPointSchema, ExtractionProfile, RunScoringKind, StepSettings } from "../types";

export type BuiltIn = "financials" | "tnfd" | "transition_plan";
export interface CustomJob { id: string; profile: "custom"; schema: DataPointSchema | null; request: string }
export interface BuiltInJob { id: BuiltIn; profile: BuiltIn }
export type Job = BuiltInJob | CustomJob;
export interface JobSettings { stepSettings: StepSettings; templateId: string | null }

export const PROFILE_META: Record<ExtractionProfile, { label: string; runType: RunScoringKind; about: string }> = {
  custom: { label: "Custom schema", runType: "extraction", about: "" },
  financials: {
    label: "Financials",
    runType: "financials",
    about:
      "Pulls disclosed business segments (name, description, revenue, operating income, assets), total CapEx, and total R&D — each with a grounded description and any disclosed category breakdown — in a single combined pass per company: one document fetch, one extractor call, one independent verifier call.",
  },
  tnfd: {
    label: "TNFD",
    runType: "tnfd",
    about:
      "Checks each of the 14 TNFD recommendations for a disclosure and extracts the core global metrics, each with citations re-verified against the source. Rules can read each recommendation as a Yes/No column (e.g. Governance_A_Disclosed).",
  },
  transition_plan: {
    label: "Transition Plan",
    runType: "transition_plan",
    about:
      "Scores each company’s climate transition disclosures against the 64 indicators of Colesanti Senni et al. (2024), separating “talk” (targets) from “walk” (verifiable activity). Rules can read each indicator as a Yes/No column (Ind_<identifier>_Disclosed).",
  },
};

const LAST = "Pick at least one profile";

export function jobLabel(j: Job): string {
  if (j.profile !== "custom") return PROFILE_META[j.profile].label;
  return j.schema ? `Custom: ${j.schema.name}` : "Custom (no schema yet)";
}

export const jobReady = (j: Job): boolean => j.profile !== "custom" || j.schema != null;

export const jobRunType = (j: Job): RunScoringKind => PROFILE_META[j.profile].runType;

function nonEmpty(before: Job[], after: Job[]): { jobs: Job[]; error: string | null } {
  return after.length ? { jobs: after, error: null } : { jobs: before, error: LAST };
}

export function toggleProfile(jobs: Job[], profile: ExtractionProfile, nextCustomId: () => string): { jobs: Job[]; error: string | null } {
  if (jobs.some((j) => j.profile === profile)) return nonEmpty(jobs, jobs.filter((j) => j.profile !== profile));
  const added: Job = profile === "custom" ? { id: nextCustomId(), profile, schema: null, request: "" } : { id: profile, profile };
  return { jobs: [...jobs, added], error: null };
}

export function addCustomJob(jobs: Job[], id: string, request: string): Job[] {
  return [...jobs, { id, profile: "custom", schema: null, request }];
}

export function removeJob(jobs: Job[], id: string): { jobs: Job[]; error: string | null } {
  return nonEmpty(jobs, jobs.filter((j) => j.id !== id));
}

export function jobsToStart(jobs: Job[], extractRuns: Record<string, string>): Job[] {
  return jobs.filter((j) => jobReady(j) && !(j.id in extractRuns));
}

export function startsText(jobCount: number, companyCount: number): string {
  return `Starts ${jobCount} ${jobCount === 1 ? "run" : "runs"} × ${companyCount} ${companyCount === 1 ? "company" : "companies"}`;
}

export async function startJobs(jobs: Job[], start: (j: Job) => Promise<string>): Promise<{ started: Record<string, string>; errors: Record<string, string> }> {
  const started: Record<string, string> = {};
  const errors: Record<string, string> = {};
  for (const j of jobs) {
    try {
      started[j.id] = await start(j);
    } catch (e) {
      errors[j.id] = e instanceof Error ? e.message : String(e);
    }
  }
  return { started, errors };
}

export function initialJobs(profile: ExtractionProfile, customId: string, request: string): Job[] {
  return [profile === "custom" ? { id: customId, profile, schema: null, request } : { id: profile, profile }];
}

const URGENCY: StageState[] = ["failed", "review", "stale", "running", "ready", "done", "skipped", "idle"];

/** The card state for several jobs: the most urgent one wins; no jobs is idle. */
export function worstStatus(states: StageState[]): StageState {
  return URGENCY.find((s) => states.includes(s)) ?? "idle";
}
