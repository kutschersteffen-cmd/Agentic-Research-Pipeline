// Theme research (dossier step 3) display rules: category labels, note headings and which actions a round allows.
// The transitions themselves are enforced by the backend (arp/themes/research.py).
import type { ResearchNote, ResearchRound, SourceCategory } from "../types.ts";

export const CATEGORY_LABEL: Record<SourceCategory, string> = {
  intergovernmental: "Intergovernmental agency",
  official_statistics: "Government or official statistics",
  central_bank_regulator: "Central bank or regulator",
  academic: "Academic research",
};

export const NOTE_SECTIONS: [keyof ResearchNote["sections"], string][] = [
  ["risks", "Risks"],
  ["opportunities", "Opportunities"],
  ["financial_relevance", "Financial relevance"],
  ["growth_potential", "Growth potential"],
  ["transmission_channels", "Transmission channels"],
];

/** No round yet, the latest note approved (a new round), or the last proposal failed (proposed again). */
export const canPropose = (r: ResearchRound | undefined) =>
  !r || r.plan_status === "proposal_failed" || r.note?.status === "approved";

export const planOpen = (r: ResearchRound | undefined) => r?.plan_status === "proposed";

/** Sources can be added to an open plan, and by hand after a failed proposal (the backend then opens the plan). */
export const canAddSource = (r: ResearchRound | undefined) => planOpen(r) || r?.plan_status === "proposal_failed";

/** What a failed proposal says: search down, or any other failure. */
export const proposalFailedText = (r: ResearchRound) =>
  r.search_unreachable
    ? "The web search could not be reached, so no sources were proposed. Add a source by hand below, or propose again."
    : "The source proposal failed. Propose again, or add a source by hand below.";

const rewritable = (r: ResearchRound) => !r.note || r.note.status === "write_failed" || r.note.status === "rejected";

export const canWriteNote = (r: ResearchRound | undefined) => !!r && r.plan_status === "approved" && rewritable(r);

export const canUpload = (r: ResearchRound | undefined) => !!r && rewritable(r);

export function unreadLines(r: ResearchRound): string[] {
  const title = (id: string) => r.sources.find((s) => s.source_id === id)?.title ?? id;
  return (r.note?.unread_sources ?? []).map((u) => `Not read: ${title(u.source_id)} (${u.reason})`);
}
