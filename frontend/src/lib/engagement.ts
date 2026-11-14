import type { EngagementIssue } from "../types";

export interface EngagementCounts {
  open: number;
  stalled: number;
  escalated: number;
}

/** Open (open or stalled), stalled, and escalated past private engagement while not resolved or closed. */
export function engagementCounts(records: { issues: Pick<EngagementIssue, "status" | "escalation_stage">[] }[]): EngagementCounts {
  const issues = records.flatMap((r) => r.issues);
  return {
    open: issues.filter((i) => i.status === "open" || i.status === "stalled").length,
    stalled: issues.filter((i) => i.status === "stalled").length,
    escalated: issues.filter((i) => i.escalation_stage !== "private_engagement" && i.status !== "resolved" && i.status !== "closed").length,
  };
}

/** The start page's engagement line: `null` while loading (unknown, never zero), "error" when the load failed. */
export function engagementLine(counts: EngagementCounts | null | "error"): string {
  if (counts === "error") return "Engagement · counts unavailable";
  const n = (k: keyof EngagementCounts) => (counts ? String(counts[k]) : "—");
  return `Engagement · ${n("open")} open · ${n("stalled")} stalled · ${n("escalated")} escalated`;
}

/** The trigger scan's note on signals whose company is not in the scanned list (they are skipped). */
export function unlistedText(count: number, ids: string[]): string {
  return count === 1
    ? `1 signal skipped: its company is not in the list (${ids.join(", ")}).`
    : `${count} signals skipped: their companies are not in the list (${ids.join(", ")}).`;
}

const DEMO_SOURCES = ["mock_voice_seed", "npx_urth_demo"];

export interface ObjectiveRow {
  description: string;
  type: string;
  status: string;
  result: string;
  demo: boolean;
}

/** One display row per objective; `demo` when the issue or the objective itself came from a demo seed. */
export function objectiveRows(issue: Pick<EngagementIssue, "objectives" | "data_source">): ObjectiveRow[] {
  const label = (v: string) => v.replace(/_/g, " ");
  return (issue.objectives ?? []).map((o) => ({
    description: o.description,
    type: label(o.objective_type),
    status: label(o.status),
    result: o.result ? label(o.result) : "—",
    demo: DEMO_SOURCES.includes(issue.data_source ?? "") || DEMO_SOURCES.includes(o.source),
  }));
}
