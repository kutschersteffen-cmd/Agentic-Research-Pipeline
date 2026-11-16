// Fund overlap tab (spec stewardship-workbench-overlap): how its numbers read.
import type { FundOverlap } from "../types";

type Fund = FundOverlap["funds"][number];
type Pair = FundOverlap["pairs"][number];

/** Counts with a comma thousands separator: 1,412. */
export const count = (n: number) => n.toLocaleString("en-US");

/** A fund's name without the bracketed source note: "DAX (public ETF holdings, …)" → "DAX". */
export const shortName = (name: string) => name.replace(/\s*\(.*\)\s*$/, "") || name;

/** A grid weight: 2 decimals, no % sign (the header says %); "—" when the fund does not hold the company. */
export const weight = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toFixed(2));

/** Tint step 0 (none) to 5 by shared weight: 0, < 20, < 40, < 60, < 80, ≥ 80 %. */
export const tintStep = (pct: number) => (pct <= 0 ? 0 : Math.min(5, Math.floor(pct / 20) + 1));

/** The pair of two funds, whichever order they were listed in. */
export function pairOf(pairs: Pair[], a: string, b: string): Pair | undefined {
  return pairs.find((p) => (p.a === a && p.b === b) || (p.a === b && p.b === a));
}

export const pairText = (p: Pair) => `${count(p.shared_companies)} · ${p.shared_weight_pct.toFixed(1)} %`;

export const pairTitle = (a: Fund, b: Fund, p: Pair) =>
  `${a.name} and ${b.name} share ${count(p.shared_companies)} companies; ${a.name} holds ${count(a.companies)}, ${b.name} holds ${count(b.companies)}.`;
