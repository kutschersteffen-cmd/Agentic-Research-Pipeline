// The Workbench side panel (spec stewardship-priority-worklist, "Side panel" and "Why is this here"): the wording of
// the Why tab and the ↑/↓ step. Pure, so the node tests pin the spec's fixed sentences.
import type { Worklist, WorklistRow } from "../types";
import { COMPONENT_LABEL, day, nextMeetingText, tierText } from "./workbench.ts";

export const PANEL_TABS = ["Why", "Company", "Engagements", "Votes", "Triggers", "Holdings", "Notes"] as const;
export type PanelTab = (typeof PANEL_TABS)[number];

export const LAST_LINE = "This score is one indicator. Sorting, filtering and selecting are your call.";

/** 1 + the number of values strictly higher (ties share a rank); null when the row has no value. */
export function rankOf<T>(rows: T[], value: (r: T) => number | null, of: T): number | null {
  const v = value(of);
  if (v === null) return null;
  return 1 + rows.filter((r) => (value(r) ?? -Infinity) > v).length;
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const sim = (o: { simulated: boolean } | null | undefined) => !!o?.simulated;

/** What the row holds for one score component, as the Value column reads it. */
export function partValue(id: string, row: WorklistRow, rows: WorklistRow[], asOf: string): { text: string; simulated: boolean } {
  const plain = (text: string) => ({ text, simulated: false });
  switch (id) {
    case "open_triggers": {
      const t = row.triggers;
      const said = (["high", "medium", "low"] as const).filter((k) => t[k] > 0).map((k) => `${t[k]} ${k}`);
      return plain(said.length ? said.join(", ") : "None");
    }
    case "holdings_weight": {
      if (row.holdings_weight_pct === null) return plain("—");
      const rank = rankOf(rows, (r) => r.holdings_weight_pct, row);
      const held = rows.filter((r) => r.holdings_weight_pct !== null).length;
      return plain(`${row.holdings_weight_pct.toFixed(3)} %  (rank ${rank} of ${held})`);
    }
    case "aum_held":
      return plain(row.aum_held_eur_m === null ? "—" : `EUR ${row.aum_held_eur_m.toFixed(1)} m`);
    case "overdue_commitments":
      return plain(String(row.overdue_commitments));
    case "broken_commitments":
      return plain(String(row.broken_commitments));
    case "escalated":
      return plain(plural(row.escalated, "engagement"));
    case "open_engagements":
      return plain(String(row.open_engagements));
    case "next_meeting":
      return plain(row.next_meeting ? nextMeetingText(row.next_meeting, asOf).text : "—");
    case "coverage_tier":
      return plain(tierText(row));
    case "transition_grade":
      return row.transition_grade
        ? { text: `${row.transition_grade.value} ${row.transition_grade.label}`, simulated: sim(row.transition_grade) }
        : plain("—");
    case "esg_score":
      return row.esg_score ? { text: Number(row.esg_score.value).toFixed(1), simulated: sim(row.esg_score) } : plain("—");
    case "controversy":
      return row.controversy ? { text: Number(row.controversy.value).toFixed(0), simulated: sim(row.controversy) } : plain("—");
    case "carbon_intensity":
      return row.carbon_intensity
        ? { text: `${Number(row.carbon_intensity.value).toFixed(0)} tCO2e/EUR m`, simulated: sim(row.carbon_intensity) }
        : plain("—");
    default:
      return plain("—");
  }
}

export type WhyLine = {
  id: string; label: string; value: { text: string; simulated: boolean }; messages: string[]; normalised: number; weight: number; points: number;
};

// Score parts whose Value carries the commitment loop's flag messages underneath.
const FLAG_KIND: Record<string, "overdue" | "broken"> = { overdue_commitments: "overdue", broken_commitments: "broken" };

/** The Why tab, worded as the spec fixes it. */
export function why(row: WorklistRow, rows: WorklistRow[], data: Pick<Worklist, "as_of" | "weights">) {
  const line = (p: WorklistRow["parts"][number]): WhyLine => ({
    id: p.id,
    label: COMPONENT_LABEL[p.id] ?? p.id,
    value: partValue(p.id, row, rows, data.as_of),
    messages: row.commitment_flags.filter((f) => f.kind === FLAG_KIND[p.id]).map((f) => f.message),
    normalised: p.normalised,
    weight: p.weight,
    points: p.points,
  });
  const w = data.weights;
  return {
    first: `${row.company} — priority score ${row.score.toFixed(1)} of 100, rank ${rankOf(rows, (r) => r.score, row)} of ${rows.length}.`,
    second:
      w.version === 0
        ? "Weights: priority_weights v0 (bundled default)."
        : `Weights: priority_weights v${w.version}, activated${w.activated_at ? ` ${day(w.activated_at)}` : ""} by ${w.activated_by ?? "unknown"}.`,
    weighted: row.parts.filter((p) => p.weight > 0 && !p.empty).map(line),
    notWeighted: row.parts.filter((p) => p.weight === 0).map(line),
    noData: row.parts.filter((p) => p.weight > 0 && p.empty).map(line),
    total: row.score.toFixed(1),
  };
}

/** The issuer ↑ (step -1) or ↓ (step 1) from `id` in the table's order; null at either end. */
export function neighbour(order: WorklistRow[], id: string, step: 1 | -1): string | null {
  const at = order.findIndex((r) => r.issuer_id === id);
  return at < 0 ? null : (order[at + step]?.issuer_id ?? null);
}
