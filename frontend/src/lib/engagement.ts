import type { EngagementIssue, S } from "../types";

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

// VOICE lists, as the API takes them (spec stewardship-commitment-loop, "Record result").
export const OBJECTIVE_RESULTS = ["achieved", "partially_achieved", "not_achieved", "deterioration", "abandoned"] as const satisfies readonly S["ObjectiveResult"][];
export const INFLUENCE_LEVELS = ["1", "2", "3", "4A", "4B", "5"] as const satisfies readonly S["InfluenceLevel"][];

/** One engagement's watch topics out of the company's list, keeping the API's newest-first order. */
export function issueTopics<T extends { engagement_id: string }>(topics: T[], issueId: string): T[] {
  return topics.filter((t) => t.engagement_id === issueId);
}
