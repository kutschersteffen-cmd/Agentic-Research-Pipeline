import type { RunManifest } from "../types";

// Shared by the Dashboard and the start page, so a run reads the same in both.
export const ACTIVE_STATUSES = new Set(["running", "pending"]);

// Run types whose flagged items go to the Review Queue.
export const REVIEWABLE_RUN_TYPES = new Set<string>(["theme", "extraction", "financials", "identity"]);

const RUN_TYPE_LABEL: Record<string, string> = {
  theme: "Thematic universe",
  extraction: "Data extraction",
  discovery: "Document discovery",
  proxy_voting: "Proxy voting",
  transition_plan: "Transition plan assessment",
  transition_barrier_refresh: "Transition barrier source refresh",
  taxonomy_research: "Taxonomy Researcher",
  calibration: "Calibration Agent",
  financials: "Company financials",
  identity: "Identity resolution",
  emerging_themes: "Emerging themes",
};

export function runTypeLabel(runType: string): string {
  return RUN_TYPE_LABEL[runType] ?? runType.replace(/_/g, " ");
}

/** Items in this run that wait on a person: flagged figures, or ballot items
 * for a voting run. Other run types have no queue, so they count zero. */
export function waitingCount(r: RunManifest): number {
  return REVIEWABLE_RUN_TYPES.has(r.run_type) || r.run_type === "proxy_voting" ? r.review_count : 0;
}

/** Items waiting on a person across these runs, by kind. Ballot items come
 * from voting runs, flagged items from runs with a review queue. The start
 * page and the sidebar counts both use this, so they always agree. */
export function waitingParts(runs: RunManifest[]): { ballots: number; review: number } {
  let ballots = 0;
  let review = 0;
  for (const r of runs) {
    if (r.run_type === "proxy_voting") ballots += r.review_count;
    else if (REVIEWABLE_RUN_TYPES.has(r.run_type)) review += r.review_count;
  }
  return { ballots, review };
}
