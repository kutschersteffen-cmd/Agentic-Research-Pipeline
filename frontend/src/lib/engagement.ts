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

type Evidence = Pick<S["EvidenceSuggestion"], "doc_title" | "page" | "quote">;

/** Where a suggestion's quote is from: `<doc_title>, page <page>`, each part left out when unknown. */
export function evidenceWhere(s: Omit<Evidence, "quote">): string {
  return [s.doc_title, s.page != null ? `page ${s.page}` : null].filter(Boolean).join(", ");
}

/** A confirmed suggestion written out: `<doc_title>, page <page>: "<quote>"`, as the API writes commitment evidence. */
export function evidenceText(s: Evidence): string {
  const where = evidenceWhere(s);
  return where ? `${where}: "${s.quote}"` : `"${s.quote}"`;
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** The line under a watch item after "Check against documents". */
export function checkLine(r: { documents: number; suggestions: number; unclear: number }): string {
  if (r.documents === 0) return "No documents on file for this company.";
  return `Checked ${plural(r.documents, "document")}: ${plural(r.suggestions, "new suggestion")}, ${r.unclear} unclear.`;
}

/** The line under a note after "Find commitments". */
export function foundLine(suggestions: number): string {
  return `Found ${plural(suggestions, "suggestion")}.`;
}

/** Record result's Save is enabled once result and outcome are set, and an influence level unless the result is abandoned. */
export function canSaveResult(result: string, level: string, outcome: string): boolean {
  return Boolean(result && outcome.trim() && (level || result === "abandoned"));
}
