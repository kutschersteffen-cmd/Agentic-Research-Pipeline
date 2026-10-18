/** Pure helpers for the Transition Barriers screens. */
import type { BarrierRating } from "../types";

// H means transition is MORE feasible (fewer barriers), so H maps to the
// positive colour. Reuses the app's existing badge vocabulary rather than
// introducing a second colour scale.
export const RATING_CLASS: Record<BarrierRating, string> = {
  H: "badge badge-high",
  M: "badge badge-mid",
  L: "badge badge-low",
};

export const RATING_LABEL: Record<BarrierRating, string> = {
  H: "High feasibility",
  M: "Moderate",
  L: "Low feasibility",
};

/** What a derived result is, as a review item says it. */
export const BARRIER_KIND_LABEL: Record<string, string> = {
  changed: "Rating change",
  unchanged: "Same rating, new evidence",
  not_rated: "Not rated",
  conflict: "Conflicting values",
};

/** Who made the cell's rating current and when: a ratified derivation, or the bundled hand rating. */
export const ratifiedLine = (c: { basis: "hand_rated" | "derived"; ratified_by: string | null; last_verified: string }): string =>
  c.basis === "derived" && c.ratified_by ? `ratified by ${c.ratified_by} ${c.last_verified}` : `hand-rated ${c.last_verified}`;

const OUTCOMES = new Set(["pass", "fail", "unknown", "mixed"]);

/** Pass, fail, unknown and mixed read as words with different line styles, not colours (colour is for H/M/L). */
export const outcomeClass = (outcome: string): string => `tb-outcome tb-outcome-${OUTCOMES.has(outcome) ? outcome : "unknown"}`;

/** The route that opens one cell's detail. */
export const cellHash = (code: string, region: string): string =>
  `#/transitionBarrier/cell/${encodeURIComponent(code)}/${encodeURIComponent(region)}`;

/** The server's message without the client's "422: " status prefix. */
export const errorDetail = (err: Error): string => err.message.replace(/^\d{3}: /, "");

/** One history entry as a sentence: what happened, without who and when (the table has those columns). */
export const historyLine = (e: {
  kind: string; rating?: string; basis?: string; fact?: string; value?: string; reason?: string; decision?: string;
}): string =>
  e.kind === "rating" ? `Rating ${e.rating} (${e.basis === "derived" ? "derived" : "hand-rated"})`
  : e.kind === "fact" ? `Fact ${e.fact}: ${e.value}`
  : e.kind === "choice" ? `Chose ${e.fact}: ${e.value} (${e.reason})`
  : `Decision: ${e.decision}`;
