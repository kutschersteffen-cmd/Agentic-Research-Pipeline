/** Value chain explorer display rules: one place for every number format the screens show. */

/** A fraction of one euro of output as cents: 0.0738 -> "7.4¢". */
export const cents = (fraction: number, digits = 1): string => `${(fraction * 100).toFixed(digits)}¢`;

export const linkText = (l: { direct: number; total: number }, mode: "total" | "direct"): string =>
  mode === "direct" ? cents(l.direct) : `${cents(l.total)} (direct ${cents(l.direct)})`;

export const tile = (v: number | null): string => (v === null ? "—" : v.toFixed(1));

// toFixed(9) first: 0.285 * 100 is 28.499999999999996, and a half must round up.
export const percent = (v: number | null): string => (v === null ? "—" : `${Math.round(Number((v * 100).toFixed(9)))}%`);

export const footprintTotal = (total: number, unit: string): string => `${total.toFixed(1)} ${unit}`;

export const homeShare = (share: number | null, regionLabel: string): string =>
  share === null ? "" : `${percent(share)} in ${regionLabel}`;

export const searchable = (q: string): boolean => q.trim() !== "";

export const nodeHash = (id: string, view?: "tree" | "footprint" | "shock"): string =>
  `#/valueChain/${encodeURIComponent(id)}${view ? `/${view}` : ""}`;

// Shocks view (spec value-chain-shocks My call 6): M EUR with one decimal and its sign, price changes with two decimals.
const MINUS = "\u2212";
export const signed = (v: number, digits = 1): string => {
  const t = Math.abs(v).toFixed(digits);
  return Number(t) === 0 ? t : `${v < 0 ? MINUS : "+"}${t}`;
};

export const pricePct = (v: number): string => `${v < 0 && Number(Math.abs(v).toFixed(2)) !== 0 ? MINUS : ""}${Math.abs(v).toFixed(2)}%`;

/** EU-27 coverage preset of the Carbon price model (GB excluded). */
export const EU27 = "AT BE BG CY CZ DE DK EE ES FI FR GR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK".split(" ");
