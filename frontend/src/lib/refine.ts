// Pure helpers for the Refine page (chat edits of an RFP or a deck).
import type { RefineHistoryItem, RefineTurn } from "../types";

export type RefineKind = "rfp" | "deck";

/** RFP ids are question ids; deck ids are 1-based slide positions. */
const label = (id: number | null, kind: RefineKind) =>
  id === null ? (kind === "rfp" ? "(no question named)" : "(no slide named)") : kind === "rfp" ? `Q${id}` : `Slide ${id}`;

/** The lines under the agent's reply: what changed, what did not and why, and figures to check. */
export function resultLines(turn: RefineTurn, kind: RefineKind = "rfp"): string[] {
  const ids = (xs: number[]) => xs.map((x) => label(x, kind)).join(", ");
  return [
    ...(turn.changed.length ? [`Changed: ${ids(turn.changed)}`] : []),
    ...turn.not_changed.map((n) => `Not changed: ${label(n.id, kind)} (${n.reason})`),
    ...(turn.check_figures.length ? [`Check figures: ${ids(turn.check_figures)}`] : []),
  ];
}

/** "<done> of <total>" while the turn runs and knows its total. */
export const progressLine = (turn: RefineTurn): string | null =>
  turn.status === "running" && turn.total > 0 ? `${turn.done} of ${turn.total}` : null;

/** The page polls every 1 s while a turn runs, else every 3 s so other people's edits show. */
export const pollMs = (turnRunning: boolean): number => (turnRunning ? 1000 : 3000);

/** The server keeps only the last 5 history turns; send no more. */
export const trimHistory = (h: RefineHistoryItem[]): RefineHistoryItem[] => h.slice(-5);

/** A slot whose text does not fit its box. */
export const overflowing = (el: HTMLElement): boolean => el.scrollHeight > el.clientHeight;
