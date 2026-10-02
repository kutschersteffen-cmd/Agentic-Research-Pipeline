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
  extractRunId: string | null;
  extractStale: boolean;
  runIds: string[];
}
export type FlowAction =
  | { type: "companies"; output: StageOutput }
  | { type: "readiness"; ready: StageOutput | null; onboard: StageOutput | null } // both null = check failed
  | { type: "recheckReady"; on: boolean }
  | { type: "setHandover"; stage: StageId; handover: Handover }
  | { type: "allAuto"; on: boolean }
  | { type: "runStarted"; stage: StageId; runId: string }
  | { type: "runFinished"; stage: StageId; status: JobStatus; flagged: number; failed: number }
  | { type: "handedOver"; stage: StageId; output: StageOutput }
  | { type: "useAnyway"; stage: StageId }
  | { type: "extractStarted"; runId: string }
  | { type: "profileChanged" };

export const STAGES: StageId[] = ["identify", "documents"];

const idleStage: Stage = { handover: "manual", state: "idle", runId: null, output: null, flagged: 0, note: null };

export const initialFlow: FlowState = {
  companies: null,
  ready: null,
  onboard: null,
  readinessNote: null,
  recheckReady: false,
  identify: idleStage,
  documents: idleStage,
  extractRunId: null,
  extractStale: false,
  runIds: [],
};

const later = (stage: StageId): StageId[] => STAGES.slice(STAGES.indexOf(stage) + 1);

/** Marks every stage matching `pick` as stale, and the extract with it. */
function stale(s: FlowState, pick: (st: Stage, id: StageId) => boolean): FlowState {
  const next = { ...s, extractStale: s.extractRunId != null };
  for (const id of STAGES) if (pick(s[id], id)) next[id] = { ...s[id], state: "stale" };
  return next;
}

export function flowReducer(s: FlowState, a: FlowAction): FlowState {
  switch (a.type) {
    case "companies": {
      const next = stale({ ...s, companies: a.output, ready: null, onboard: null, readinessNote: null }, (st) => st.runId != null);
      // A stage auto-skipped for "Nothing to onboard" is not a user choice, so a new list revives it.
      for (const id of STAGES) {
        const st = next[id];
        if (st.state === "skipped" && st.handover !== "skip") next[id] = { ...st, state: "idle", note: null };
      }
      return next;
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
      if (onboard?.count === 0) {
        for (const id of STAGES) {
          if (s[id].state === "idle") next[id] = { ...s[id], state: "skipped", note: "Nothing to onboard" };
        }
      }
      return next;
    }
    case "recheckReady":
      return stale({ ...s, recheckReady: a.on }, (st) => st.runId != null);
    case "setHandover":
      return {
        ...s,
        [a.stage]: {
          ...s[a.stage],
          handover: a.handover,
          state: a.handover === "skip" ? "skipped" : s[a.stage].state === "skipped" ? "idle" : s[a.stage].state,
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
      const bad = a.flagged + a.failed;
      const [state, note]: [StageState, string | null] =
        a.status === "failed" ? ["failed", "Run failed"]
        : a.status === "cancelled" ? ["review", "Stopped"]
        : bad > 0 ? ["review", `${bad} companies need review`]
        : ["ready", null];
      return { ...s, [a.stage]: { ...s[a.stage], state, note, flagged: a.flagged } };
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
      return s[a.stage].state === "stale" ? { ...s, [a.stage]: { ...s[a.stage], state: "done" } } : s;
    case "extractStarted":
      return { ...s, extractRunId: a.runId, runIds: [...s.runIds, a.runId], extractStale: false };
    case "profileChanged":
      return { ...s, extractRunId: null, extractStale: false };
  }
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

export const valueOrigin = (d?: ReviewDecision): "system" | "edited" => (d?.decision === "edit" ? "edited" : "system");

export const runScope = (m: RunManifest): "batch" | "single" => (m.company_count === 1 ? "single" : "batch");

export const runEndedAt = (m: RunManifest): string | null =>
  m.status === "running" || m.status === "pending" ? null : m.updated_at;

export function companiesToCheck(results: DiscoveryCompanyResult[], uploaded: Set<string>): string[] {
  const empty = results.filter((r) => r.documents_found.length === 0).map((r) => r.company_id);
  return [...new Set([...empty, ...uploaded])];
}

export interface DocRow { companyId: string; name: string; discovered: number; onFile: number; uploaded: boolean; flagged: boolean }

export function docRows(results: DiscoveryCompanyResult[], onFile: Record<string, number>, uploaded: Set<string>): DocRow[] {
  return results.map((r) => {
    const discovered = r.documents_found.length;
    const files = onFile[r.company_id] ?? discovered;
    return {
      companyId: r.company_id,
      name: r.name,
      discovered,
      onFile: files,
      uploaded: uploaded.has(r.company_id),
      flagged: discovered === 0 && files === 0,
    };
  });
}
