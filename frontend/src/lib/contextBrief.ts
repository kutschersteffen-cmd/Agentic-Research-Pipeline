import type { BriefEvidence, ContextBrief } from "../types.ts";

const ACTIONS = ["capex", "hiring", "orders", "capacity", "partnership"] as const;

/** `x` to `digits` decimals, rounded half away from zero (toFixed alone rounds 1.005 down). */
export function fixed(x: number, digits: number): string {
  const scaled = Number((Math.abs(x) * 10 ** digits).toPrecision(12));
  return ((Math.sign(x) * Math.round(scaled)) / 10 ** digits).toFixed(digits);
}

export function factsLine(brief: ContextBrief): string {
  const f = brief.facts;
  const dates = f.first_seen == null && f.last_seen == null ? "Mention dates unknown" : `Mentions ${f.first_seen} to ${f.last_seen}`;
  return `${dates} · ${f.independent_sources} independent sources · ${f.company_count} companies · velocity ${fixed(f.velocity, 2)}`;
}

export function actionsLine(brief: ContextBrief): string {
  const counts = ACTIONS.filter((a) => (brief.facts.action_counts[a] ?? 0) > 0).map((a) => `${a} ${brief.facts.action_counts[a]}`);
  return `Corporate actions: ${counts.join(", ")}`;
}

// The SEC lookup stores a fraction (0.25 = +25%), as xbrl_corroboration does.
const signedPct = (x: number | null) => (x == null ? "n/a" : `${x >= 0 ? "+" : ""}${fixed(x * 100, 1)}%`);

export function financialsLine(item: Extract<BriefEvidence, { kind: "financials" }>, name: string): string {
  return `${name}: CapEx ${signedPct(item.capex_pct_change)}, R&D ${signedPct(item.rnd_pct_change)} (SEC filings)`;
}

/** The `n` of `E<n>`, the number a marker and the evidence list show. */
export const evidenceNumber = (evidenceId: string) => Number(evidenceId.slice(1));

export function companyNames(brief: ContextBrief, ids: string[]): string {
  const names = new Map(brief.companies.map((c) => [c.company_id, c.name]));
  return ids.map((id) => names.get(id) ?? id).join(", ");
}

export const NO_BRIEF = "No context brief: this run predates briefs.";
