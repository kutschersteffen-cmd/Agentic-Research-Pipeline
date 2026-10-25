import type { ReviewableRunKind, RunManifest } from "../types";

// Shared by the Dashboard and the start page, so a run reads the same in both.
export const ACTIVE_STATUSES = new Set(["running", "pending"]);

// Run types whose flagged items go to the Review Queue.
export const REVIEWABLE_RUN_TYPES: ReadonlySet<string> = new Set<ReviewableRunKind>(["theme", "extraction", "financials", "identity", "transition_plan", "tnfd", "transition_barrier_derivation"]);

// Run types the backend can resume, and the statuses a resume applies to.
export const RESUMABLE_RUN_TYPES: ReadonlySet<string> = new Set([
  "theme",
  "extraction",
  "financials",
  "tnfd",
  "identity",
  "discovery",
  "xbrl_fetch",
]);
/** The kind Decision Studio and the process map file a run under: a transition-plan preset run is an extraction run on the preset schema. */
export const decisionRunType = (r: RunManifest): string =>
  r.run_type === "extraction" && r.params?.schema_id === "transition_plan_indicators" ? "transition_plan" : r.run_type;

const RESUMABLE_STATUSES = new Set(["failed", "partially_completed", "cancelled"]);

export const NEEDS_ATTENTION_DAYS = 14;

export const canResumeRun = (runType: string, status: string): boolean =>
  RESUMABLE_RUN_TYPES.has(runType) && RESUMABLE_STATUSES.has(status);

/** Resumable runs that failed or stopped part-way within the last 14 days, in input order. A future updated_at counts as recent. */
export function needsAttentionRuns(runs: RunManifest[], now: Date): RunManifest[] {
  const maxAge = NEEDS_ATTENTION_DAYS * 24 * 3600 * 1000;
  return runs.filter((r) => {
    if (!RESUMABLE_RUN_TYPES.has(r.run_type) || (r.status !== "failed" && r.status !== "partially_completed")) return false;
    const age = now.getTime() - Date.parse(r.updated_at);
    return !Number.isNaN(age) && age <= maxAge;
  });
}

/** Statuses whose Run History row opens a failure-details panel. */
export const hasFailureDetails = (status: string): boolean => status === "failed" || status === "partially_completed";

/** Failed or partially completed runs the backend can resume, in input order. */
export const resumableFailedRuns = (runs: RunManifest[]): RunManifest[] =>
  runs.filter((r) => hasFailureDetails(r.status) && canResumeRun(r.run_type, r.status));

/** The line shown after a "Resume all failed" pass. */
export const resumeSummary = (total: number, refused: { runId: string; message: string }[]): string =>
  `Resumed ${total - refused.length} of ${total}.` +
  (refused.length ? ` Refused: ${refused.map((f) => `${f.runId}: ${f.message}`).join("; ")}` : "");

/** Company errors a failure-details panel lists before it says "and N more". */
export const COMPANY_ERRORS_SHOWN = 50;

/** Oldest first; an undated row goes after every dated one. */
export const compareSince = (a: string | null, b: string | null): number =>
  a === null || b === null ? Number(a === null) - Number(b === null) : a.localeCompare(b);

export const RUN_TYPE_LABEL: Record<string, string> = {
  theme: "Thematic universe",
  extraction: "Data extraction",
  discovery: "Document discovery",
  proxy_voting: "Proxy voting",
  transition_plan: "Transition plan assessment",
  transition_barrier_refresh: "Transition barrier source refresh",
  transition_barrier_derivation: "Transition barrier derivation",
  taxonomy_research: "Taxonomy Researcher",
  calibration: "Calibration Agent",
  financials: "Company financials",
  identity: "Identity resolution",
  emerging_themes: "Emerging themes",
  tnfd: "TNFD extraction",
};

/** A run's timestamp as tables show it: date and minute, no seconds. */
export function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** An extraction run started on draft schema fields (manifest params.trial): its results are not final. */
export const isTrialRun = (r: Pick<RunManifest, "params"> | null | undefined): boolean => r?.params?.trial === true;

export const TRIAL_TITLE = "Trial run: the schema had draft fields, so these results are not final.";

export function runTypeLabel(runType: string): string {
  return RUN_TYPE_LABEL[runType] ?? runType.replace(/_/g, " ");
}

/** Items in this run that wait on a person: flagged figures, or ballot items
 * for a voting run. Other run types have no queue, so they count zero. */
export function waitingCount(r: RunManifest): number {
  return REVIEWABLE_RUN_TYPES.has(r.run_type) || r.run_type === "proxy_voting" ? r.review_count : 0;
}

/** The wait line for a run parked on an Anthropic message batch. */
export function batchWaitText(wait: NonNullable<RunManifest["batch_wait"]>): string {
  const t = new Date(wait.submitted_at);
  const hhmm = `${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`;
  return `Waiting on batch · ${wait.request_count.toLocaleString("en-US")} requests · submitted ${hhmm} · Anthropic usually finishes within an hour`;
}

/** One row per proxy voting run with ballots waiting on a person, for the start page's Needs you list. */
export function ballotRows(runs: RunManifest[]): { runId: string; count: number; what: string; href: string }[] {
  return runs
    .filter((r) => r.run_type === "proxy_voting" && r.review_count > 0)
    .map((r) => ({
      runId: r.run_id,
      count: r.review_count,
      what: `Proxy voting run ${r.run_id}: ${r.review_count === 1 ? "1 ballot" : `${r.review_count} ballots`} to decide`,
      href: `#/voting/${encodeURIComponent(r.run_id)}`,
    }));
}
