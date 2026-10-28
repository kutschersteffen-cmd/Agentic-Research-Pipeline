/** Value chain explorer display rules: one place for every number format the screens show. */

/** A fraction of one euro of output as cents: 0.0738 -> "7.4¢". */
export const cents = (fraction: number, digits = 1): string => `${(fraction * 100).toFixed(digits)}¢`;

export const linkText = (l: { direct: number; total: number }, mode: "total" | "direct"): string =>
  mode === "direct" ? cents(l.direct) : `${cents(l.total)} (direct ${cents(l.direct)})`;

export const tile = (v: number | null): string => (v === null ? "—" : v.toFixed(1));

// toFixed(9) first: 0.285 * 100 is 28.499999999999996, and a half must round up.
export const percent = (v: number | null, digits = 0): string =>
  v === null ? "—" : `${(Math.round(Number((v * 100 * 10 ** digits).toFixed(9))) / 10 ** digits).toFixed(digits)}%`;

export const footprintTotal = (total: number, unit: string): string => `${total.toFixed(1)} ${unit}`;

/** Tonnes extracted, rounded to one decimal first: 999.94 -> "999.9 t", 999.96 -> "1,000 t". */
export const tonnes = (t: number): string => {
  const r = Math.round(t * 10) / 10;
  return `${r < 1000 ? r.toFixed(1) : Math.round(r).toLocaleString("en-US")} t`;
};

export const homeShare = (share: number | null, regionLabel: string): string =>
  share === null ? "" : `${percent(share)} in ${regionLabel}`;

export const searchable = (q: string): boolean => q.trim() !== "";

export const nodeHash = (id: string, view?: "tree" | "footprint"): string =>
  `#/valueChain/${encodeURIComponent(id)}${view ? `/${view}` : ""}`;

/** A share as percent with one decimal: 0.55 -> "55.0%". */
export const pct1 = (v: number): string => percent(v, 1);

export const portfolioHash = (id?: string): string => `#/valueChain/portfolio${id ? `/${encodeURIComponent(id)}` : ""}`;

/** One rule part the current build has no node for, as the link editor lists it. */
export const unresolvedText = (part: { icio_code?: string; region?: string; sector?: string; share: number }): string =>
  `Not in this edition: ${part.icio_code ?? `${part.region} · ${part.sector}`} ${pct1(part.share)}`;

/** "Copper and nickel mining: 35.0% of NAV directly · 51.9% of upstream". */
export const activityLine = (a: { name: string; direct_weight: number; upstream_share: number | null }): string =>
  `${a.name}: ${pct1(a.direct_weight)} of NAV directly · ${a.upstream_share === null ? "—" : pct1(a.upstream_share)} of upstream`;
