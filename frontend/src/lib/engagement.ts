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

const DEMO_SOURCES = ["mock_voice_seed", "npx_urth_demo"];

/** An objective is demo data when it, or the issue it sits under, came from a demo seed (`Demo data` label). */
export function isDemo(issue: Pick<EngagementIssue, "data_source">, objective: { source?: string | null }): boolean {
  return DEMO_SOURCES.includes(issue.data_source ?? "") || DEMO_SOURCES.includes(objective.source ?? "");
}

/** The issue header's `Demo data` chip: the issue, or any of its objectives, came from a demo seed. */
export function isDemoIssue(issue: Pick<EngagementIssue, "data_source" | "objectives">): boolean {
  return isDemo(issue, {}) || issue.objectives.some((o) => isDemo(issue, o));
}

/** A code as words: `in_progress` -> `in progress`. */
export function fmt(s: string): string {
  return s.replace(/_/g, " ");
}

/** A due date as stored, or only its date when it is an ISO timestamp (`2026-12-31T00:00:00` -> `2026-12-31`). */
export function dueText(date: string): string {
  return /^\d{4}-\d{2}-\d{2}T/.test(date) ? date.slice(0, 10) : date;
}

/** The "Approve N routine" dialog's flag list: `<company>: <message>` for each watch flag of a company in the batch, once. */
export function batchFlagLines(ballots: { company_id: string; name: string; watch_flags?: { message: string }[] }[], companyIds: string[]): string[] {
  const lines = ballots.filter((b) => companyIds.includes(b.company_id)).flatMap((b) => (b.watch_flags ?? []).map((f) => `${b.name}: ${f.message}`));
  return [...new Set(lines)];
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

/** Spacing, case and typographic quotes and dashes, as PDF-to-text changes them, removed before comparing a quote. */
const normalise = (t: string) =>
  t.replace(/[‘’]/g, "'").replace(/[“”„]/g, '"').replace(/[–—‑−]/g, "-").replace(/\s+/g, " ").toLowerCase();

/** Whether a found commitment's quote is word for word in its note (spec stewardship-decisions-round-2, area 2). */
export function quoteInNote(quote: string, summary: string): boolean {
  const q = normalise(quote).trim();
  return q !== "" && normalise(summary).includes(q);
}

/** The id of a correspondence entry's `<li>` in the issue panel, so a found commitment can move focus to its note. */
export const noteAnchor = (entryId: string) => `note-${entryId}`;

/** One load of a company's suggestions. `loaded` is null on any error; `error` is the error's text ("<status>: <detail>"),
 * except on the file store's 409, which only means there are no suggestions there. */
export async function loadSuggestions<T>(
  list: (status: "pending" | "confirmed") => Promise<{ suggestions: T[] }>,
): Promise<{ loaded: { pending: T[]; confirmed: T[] } | null; error: string | null }> {
  try {
    const [p, c] = await Promise.all([list("pending"), list("confirmed")]);
    return { loaded: { pending: p.suggestions, confirmed: c.suggestions }, error: null };
  } catch (err) {
    const message = (err as Error).message;
    return { loaded: null, error: message.startsWith("409:") ? null : message };
  }
}

/** The found-commitment card's header; with the note unknown it names no date. */
export function foundHeader(note?: { type: string; activity_type?: string | null; date: string }): string {
  return note ? `Argus found a commitment in the ${note.activity_type ?? note.type} of ${note.date.slice(0, 10)}` : "Argus found a commitment in a note";
}

/** Record result's Save is enabled once result and outcome are set, and an influence level unless the result is abandoned. */
export function canSaveResult(result: string, level: string, outcome: string): boolean {
  return Boolean(result && outcome.trim() && (level || result === "abandoned"));
}
