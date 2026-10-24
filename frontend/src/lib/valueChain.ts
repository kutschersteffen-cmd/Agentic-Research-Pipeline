/** Value chain explorer display rules: one place for every number format the screens show. */

/** A fraction of one euro of output as cents: 0.0738 -> "7.4¢". */
export const cents = (fraction: number, digits = 1): string => `${(fraction * 100).toFixed(digits)}¢`;

export const linkText = (l: { direct: number; total: number }, mode: "total" | "direct"): string =>
  mode === "direct" ? cents(l.direct) : `${cents(l.total)} (direct ${cents(l.direct)})`;

export const tile = (v: number | null): string => (v === null ? "—" : v.toFixed(1));

// toFixed(9) first: 0.845 * 100 is 84.49999..., and a half must round up.
export const percent = (v: number | null): string => (v === null ? "—" : `${Math.round(Number((v * 100).toFixed(9)))}%`);

export const footprintTotal = (total: number, unit: string): string => `${total.toFixed(1)} ${unit}`;

export const homeShare = (share: number | null, regionLabel: string): string =>
  share === null ? "" : `${percent(share)} in ${regionLabel}`;

export const searchable = (q: string): boolean => q.trim() !== "";

export const nodeHash = (id: string, view?: "tree" | "footprint"): string =>
  `#/valueChain/${encodeURIComponent(id)}${view ? `/${view}` : ""}`;
