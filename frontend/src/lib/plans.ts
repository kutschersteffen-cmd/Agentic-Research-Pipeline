/** Research Orchestrator plans as /api/plans serves them (plain dicts on the backend, so typed here). */
export type PlanStatus = "draft" | "approved" | "running" | "awaiting_review" | "done" | "failed" | "cancelled";
export type CallStatus = "pending" | "running" | "awaiting_review" | "done" | "failed" | "cancelled";

export interface DryRunStep { seq: number; kind: string; params: Record<string, unknown>; depends_on: number | null }
export interface PlanCall { seq: number; kind: string; params: Record<string, unknown>; status: CallStatus; run_id: string | null; result_ref: string | null }
export interface Plan {
  id: string;
  brief: string;
  script: string;
  dry_run: DryRunStep[];
  status: PlanStatus;
  approved_by: string | null;
  approved_at: string | null;
  error: string | null;
  calls?: PlanCall[];
}

export const ACTIVE: ReadonlySet<PlanStatus> = new Set(["running", "awaiting_review"]);

/** One row per planned step: the stored call once the run reached it, else `pending`. */
export function stepRows(plan: Plan): { step: DryRunStep; status: CallStatus; call: PlanCall | null }[] {
  const bySeq = new Map((plan.calls ?? []).map((c) => [c.seq, c]));
  const rows = plan.dry_run.map((step) => {
    const call = bySeq.get(step.seq) ?? null;
    return { step, status: call?.status ?? ("pending" as CallStatus), call };
  });
  // A data-dependent loop can make more calls than the dry run showed: list those too.
  for (const call of plan.calls ?? []) {
    if (call.seq > plan.dry_run.length) rows.push({ step: { seq: call.seq, kind: call.kind, params: call.params, depends_on: null }, status: call.status, call });
  }
  return rows;
}

/** Where a finished step's result is shown: its run in Run History, or the screen that owns a run-less result. */
export function resultHref(call: PlanCall): string | null {
  if (call.run_id) return `#/history/${encodeURIComponent(call.run_id)}`;
  if (call.result_ref?.startsWith("report:")) return "#/reporting";
  if (call.result_ref?.startsWith("decision:")) return "#/decision";
  return null;
}
