import type { CompanyRef, DiscoveryCompanyResult, JobStatus, ReviewDecision, RunManifest } from "../types";

export type StageId = "identify" | "documents";
export type FlowStep = "companies" | StageId | "schema" | "extract";
export type Handover = "manual" | "auto" | "skip";
export type StageState = "idle" | "running" | "review" | "ready" | "done" | "skipped" | "stale" | "failed";
/** `companies` is set when the output was built from records (readiness, handovers). */
export interface StageOutput { path: string; count: number; companies?: CompanyRef[] }
export interface Stage {
  handover: Handover;
  state: StageState;
  runId: string | null;
  output: StageOutput | null;
  flagged: number;
  note: string | null;
}
export interface FlowState {
  companies: StageOutput | null;
  ready: StageOutput | null;
  onboard: StageOutput | null;
  readinessNote: string | null;
  recheckReady: boolean;
  identify: Stage;
  documents: Stage;
  /** Extraction run id per job id. */
  extractRuns: Record<string, string>;
  extractStale: boolean;
  /** Jobs re-run since the inputs went stale; a retry skips them. */
  freshJobs: string[];
  runIds: string[];
}
export type FlowAction =
  | { type: "companies"; output: StageOutput }
  | { type: "readiness"; ready: StageOutput | null; onboard: StageOutput | null } // both null = check failed
  | { type: "recheckReady"; on: boolean }
  | { type: "setHandover"; stage: StageId; handover: Handover }
  | { type: "allAuto"; on: boolean }
  | { type: "runStarted"; stage: StageId; runId: string }
  /** `note` set = the results couldn't be checked; the stage holds for review with that note. */
  | { type: "runFinished"; stage: StageId; status: JobStatus; flagged: number; failed: number; note?: string }
  | { type: "handedOver"; stage: StageId; output: StageOutput }
  | { type: "useAnyway"; stage: StageId }
  | { type: "extractStarted"; job: string; runId: string }
  /** One job's run restarted from a step: the inputs did not change, so a stale flag stays. */
  | { type: "extractRestarted"; job: string; runId: string }
  /** Every job of a stale re-run started, so nothing old is left looking current. */
  | { type: "staleCleared" }
  | { type: "jobsChanged"; jobIds: string[] };

export const STAGES: StageId[] = ["identify", "documents"];

/** What a mounted stage component lets its parent trigger (the overview chart's Start / Continue). */
export interface StageHandle { start(): void; carryOn(): void }

const idleStage: Stage = { handover: "manual", state: "idle", runId: null, output: null, flagged: 0, note: null };

export const initialFlow: FlowState = {
  companies: null,
  ready: null,
  onboard: null,
  readinessNote: null,
  recheckReady: false,
  identify: idleStage,
  documents: idleStage,
  extractRuns: {},
  extractStale: false,
  freshJobs: [],
  runIds: [],
};

const later = (stage: StageId): StageId[] => STAGES.slice(STAGES.indexOf(stage) + 1);

/** Marks every stage matching `pick` as stale, and the extract with it. */
function stale(s: FlowState, pick: (st: Stage, id: StageId) => boolean): FlowState {
  const next = { ...s, extractStale: Object.keys(s.extractRuns).length > 0, freshJobs: [] };
  for (const id of STAGES) if (pick(s[id], id)) next[id] = { ...s[id], state: "stale" };
  return next;
}

/** A stage auto-skipped for "Nothing to onboard" is not a user choice, so a new input revives it. */
function unskip(s: FlowState): FlowState {
  const next = { ...s };
  for (const id of STAGES) {
    const st = s[id];
    if (st.state === "skipped" && st.handover !== "skip") next[id] = { ...st, state: "idle", note: null };
  }
  return next;
}

export function flowReducer(s: FlowState, a: FlowAction): FlowState {
  switch (a.type) {
    case "companies": {
      return unskip(stale({ ...s, companies: a.output, ready: null, onboard: null, readinessNote: null }, (st) => st.runId != null));
    }
    case "readiness": {
      const failed = a.ready == null && a.onboard == null;
      const onboard = failed ? s.companies : a.onboard;
      const next: FlowState = {
        ...s,
        ready: failed ? null : a.ready,
        onboard,
        readinessNote: failed ? "Couldn't check stored documents; all companies will be onboarded" : null,
      };
      if (!s.recheckReady && onboard?.count === 0) {
        for (const id of STAGES) {
          if (s[id].state === "idle") next[id] = { ...s[id], state: "skipped", note: "Nothing to onboard" };
        }
      }
      return next;
    }
    case "recheckReady":
      return unskip(stale({ ...s, recheckReady: a.on }, (st) => st.runId != null));
    case "setHandover":
      return {
        ...s,
        [a.stage]: {
          ...s[a.stage],
          handover: a.handover,
          ...(a.handover === "skip"
            ? { state: "skipped" as const }
            : s[a.stage].state === "skipped" ? { state: "idle" as const, note: null } : {}),
        },
      };
    case "allAuto": {
      const next = { ...s };
      for (const id of STAGES) if (s[id].handover !== "skip") next[id] = { ...s[id], handover: a.on ? "auto" : "manual" };
      return next;
    }
    case "runStarted": {
      const next = stale(
        { ...s, runIds: [...s.runIds, a.runId] },
        (st, id) => later(a.stage).includes(id) && (st.state === "done" || st.state === "ready" || st.state === "review"),
      );
      next[a.stage] = { ...s[a.stage], state: "running", runId: a.runId };
      return next;
    }
    case "runFinished": {
      const [state, note]: [StageState, string | null] =
        a.status === "failed" ? ["failed", "Run failed"]
        : a.status === "cancelled" ? ["review", "Stopped"]
        : a.note ? ["review", a.note]
        : a.failed === 0 && a.flagged > 0 ? ["review", `${a.flagged} companies need review`]
        : a.failed > 0 ? ["review", [a.flagged && `${a.flagged} need review`, `${a.failed} failed`].filter(Boolean).join(" · ")]
        : ["ready", null];
      const st = s[a.stage];
      // A run that finishes after its inputs changed stays stale; only its counts update.
      return { ...s, [a.stage]: { ...st, state: st.state === "stale" ? "stale" : state, note, flagged: a.flagged } };
    }
    case "handedOver": {
      const st = s[a.stage];
      return {
        ...s,
        [a.stage]: a.output.count === 0
          ? { ...st, state: "review", note: "No companies to carry forward" }
          : { ...st, state: "done", output: a.output },
      };
    }
    case "useAnyway":
      return s[a.stage].state === "stale" && s[a.stage].output != null ? { ...s, [a.stage]: { ...s[a.stage], state: "done" } } : s;
    case "extractStarted":
      return { ...s, extractRuns: { ...s.extractRuns, [a.job]: a.runId }, runIds: [...s.runIds, a.runId], extractStale: false, freshJobs: [] };
    case "extractRestarted": {
      const fresh = s.extractStale && !s.freshJobs.includes(a.job) ? [...s.freshJobs, a.job] : s.freshJobs;
      return { ...s, extractRuns: { ...s.extractRuns, [a.job]: a.runId }, runIds: [...s.runIds, a.runId], freshJobs: fresh };
    }
    case "staleCleared":
      return { ...s, extractStale: false, freshJobs: [] };
    case "jobsChanged": {
      const kept = Object.fromEntries(Object.entries(s.extractRuns).filter(([k]) => a.jobIds.includes(k)));
      return { ...s, extractRuns: kept, extractStale: s.extractStale && Object.keys(kept).length > 0, freshJobs: s.freshJobs.filter((j) => a.jobIds.includes(j)) };
    }
  }
}

/** The most recently started extraction run that is still tracked. */
export function latestExtractRun(s: FlowState): string | null {
  const live = Object.values(s.extractRuns);
  return s.runIds.findLast((id) => live.includes(id)) ?? null;
}

export function stageInput(s: FlowState, stage: StageId): StageOutput | null {
  if (stage === "identify") return s.recheckReady || !s.ready && !s.onboard ? s.companies : s.onboard;
  if (s.identify.state === "done") return s.identify.output;
  return s.identify.state === "skipped" ? stageInput(s, "identify") : null;
}

/** The share that went through onboarding: the documents output, or its input when documents is skipped. */
function onboardedShare(s: FlowState): StageOutput | null {
  if (s.documents.state === "done") return s.documents.output;
  return s.documents.state === "skipped" ? stageInput(s, "documents") : null;
}

/** How many onboarding companies Extract would leave out right now (their share isn't handed over yet). */
export const pendingOnboard = (s: FlowState): number => (onboardedShare(s) ? 0 : stageInput(s, "identify")?.count ?? 0);

export function extractInputs(s: FlowState): StageOutput[] {
  const share = onboardedShare(s);
  return [
    !s.recheckReady && s.ready && s.ready.count > 0 ? s.ready : null,
    share && share.count > 0 ? share : null,
  ].filter((o): o is StageOutput => o != null);
}

export function mergeCompanies(outputs: StageOutput[]): CompanyRef[] {
  const seen = new Map<string, CompanyRef>();
  for (const o of outputs) for (const c of o.companies ?? []) if (!seen.has(c.company_id)) seen.set(c.company_id, c);
  return [...seen.values()];
}

export const autoContinueDue = (stage: Stage): boolean => stage.handover === "auto" && stage.state === "ready";

export interface ReviewTileCounts { pending: number; approved: number; edited: number; rejected: number; flagged: number }

export function reviewCounts(pending: number, decisions: ReviewDecision[], flagged: number): ReviewTileCounts {
  const n = (d: ReviewDecision["decision"]) => decisions.filter((x) => x.decision === d).length;
  return { pending, approved: n("approve"), edited: n("edit"), rejected: n("reject"), flagged };
}

const TILE_DECISION = { approved: "approve", edited: "edit", rejected: "reject" } as const;

/** Whether an item belongs under a status tile: pending = flagged and undecided, flagged = every flagged item. */
export function matchesTile(filter: keyof ReviewTileCounts | null | undefined, flagged: boolean, d?: ReviewDecision): boolean {
  if (!filter) return true;
  if (filter === "flagged") return flagged;
  if (filter === "pending") return flagged && !d;
  return d?.decision === TILE_DECISION[filter];
}

/** The reviewer's replacement value as text, or undefined when the decision is not an edit. */
export const editedText = (d?: ReviewDecision): string | undefined =>
  d?.decision === "edit" && d.edited_value?.value != null ? String(d.edited_value.value) : undefined;

export const valueOrigin = (d?: ReviewDecision): "system" | "edited" => (d?.decision === "edit" ? "edited" : "system");

export const runScope = (m: RunManifest): "batch" | "single" => (m.company_count === 1 ? "single" : "batch");

export const runEndedAt = (m: RunManifest): string | null =>
  m.status === "running" || m.status === "pending" ? null : m.updated_at;

export interface DocRow {
  companyId: string;
  name: string;
  discovered: number;
  onFile: number;
  uploaded: boolean;
  flagged: boolean;
  searched: boolean;
  homepageUsed: string | null;
  crawlError: string | null;
  unreachable: boolean;
}

/** One row per input company; discovery results are left-joined, so a company with no result row reads 0 discovered. */
export function docRows(
  companies: CompanyRef[],
  results: DiscoveryCompanyResult[],
  onDisk: Record<string, number>,
  uploaded: Set<string>,
): DocRow[] {
  const byId = new Map(results.map((r) => [r.company_id, r]));
  return companies.map((c) => {
    const r = byId.get(c.company_id);
    const discovered = r?.documents_found.length ?? 0;
    const files = onDisk[c.company_id] ?? discovered;
    return {
      companyId: c.company_id,
      name: c.name,
      discovered,
      onFile: files,
      uploaded: uploaded.has(c.company_id),
      flagged: discovered === 0 && files === 0,
      searched: r != null,
      homepageUsed: r?.homepage_used ?? null,
      crawlError: r?.crawl_error ?? null,
      unreachable: r?.homepage_unreachable ?? false,
    };
  });
}

/** Why a flagged row found nothing, from the crawl diagnostics. */
export function flagReason(r: DocRow): string {
  if (!r.searched) return "No discovery result";
  if (r.unreachable || r.crawlError) return `Site unreachable: ${r.crawlError ?? "no response"}`;
  if (!r.homepageUsed) return "No documents · no homepage known";
  return `No documents found on ${r.homepageUsed}`;
}
