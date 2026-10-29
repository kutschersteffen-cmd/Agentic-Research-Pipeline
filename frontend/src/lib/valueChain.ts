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

export const nodeHash = (id: string, view?: "tree" | "footprint" | "shock" | "exposure"): string =>
  `#/valueChain/${encodeURIComponent(id)}${view ? `/${view}` : ""}`;

/** The Shocks view with its portfolio lens, so a reload or a shared link keeps the chosen portfolio. */
export const shockHash = (id: string, portfolio: string): string =>
  `${nodeHash(id, "shock")}${portfolio ? `/${encodeURIComponent(portfolio)}` : ""}`;

// Shocks view (spec value-chain-shocks My call 6): M EUR with one decimal and its sign, price changes with two decimals.
const MINUS = "\u2212";
export const signed = (v: number, digits = 1): string => {
  const t = Math.abs(v).toFixed(digits);
  return Number(t) === 0 ? t : `${v < 0 ? MINUS : "+"}${t}`;
};

export const pricePct = (v: number): string => `${v < 0 && Number(Math.abs(v).toFixed(2)) !== 0 ? MINUS : ""}${Math.abs(v).toFixed(2)}%`;

/** The Shocks view's portfolio lens: "Portfolio output change −8.23%"; "—" when nothing in the portfolio is linked. */
export const lensLine = (kind: "output" | "price", v: number | null | undefined): string =>
  `Portfolio ${kind} change ${v == null ? "—" : pricePct(v)}`;

/** EU-27 coverage preset of the Carbon price model (GB excluded). */
export const EU27 = "AT BE BG CY CZ DE DK EE ES FI FR GR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK".split(" ");
/** A share as percent with one decimal: 0.55 -> "55.0%". */
export const pct1 = (v: number): string => percent(v, 1);

export const portfolioHash = (id?: string): string => `#/valueChain/portfolio${id ? `/${encodeURIComponent(id)}` : ""}`;

/** One rule part the current build has no node for, as the link editor lists it. */
export const unresolvedText = (part: { icio_code?: string; region?: string; sector?: string; share: number }): string =>
  `Not in this edition: ${part.icio_code ?? `${part.region} · ${part.sector}`} ${pct1(part.share)}`;

/** "Copper and nickel mining: 35.0% of NAV directly · 51.9% of upstream". */
export const activityLine = (a: { name: string; direct_weight: number; upstream_share: number | null }): string =>
  `${a.name}: ${pct1(a.direct_weight)} of NAV directly · ${a.upstream_share === null ? "—" : pct1(a.upstream_share)} of upstream`;

/** Revenue in M EUR with one decimal: 24.7261 -> "24.7 M EUR". */
export const meur = (v: number): string => `${v.toFixed(1)} M EUR`;

export const recipesHash = (rid?: string): string => `#/valueChain/recipes${rid ? `/${encodeURIComponent(rid)}` : ""}`;

/** The exposure view of a target (a node id or recipe:<rid>), with one seller's routes when `from` is given. */
export const exposureHash = (target: string, from?: string): string => {
  const base = target.startsWith("recipe:") ? `${recipesHash(target.slice("recipe:".length))}/exposure` : nodeHash(target, "exposure");
  return from ? `${base}/${encodeURIComponent(from)}` : base;
};

/** A route as its labels joined by arrows; ids without a label show as themselves. */
export const routeText = (nodes: string[], labels: Record<string, string>): string => nodes.map((n) => labels[n] ?? n).join(" → ");

/** A picker query: "copper, CN" searches "copper" and keeps hits whose region code or label is "CN"; no comma, no filter.
 * Many sector names hold a comma too, so `pickerHits` falls back to the whole text when the filter keeps nothing. */
export const nodeQuery = (q: string): { q: string; region: string | null } => {
  const at = q.lastIndexOf(",");
  const head = at < 0 ? "" : q.slice(0, at);
  const region = at < 0 ? "" : q.slice(at + 1).trim().toLowerCase();
  return region && head.trim() ? { q: head, region } : { q, region: null };
};

export const inRegion = (n: { region: string; region_label: string }, region: string | null): boolean =>
  region === null || n.region.toLowerCase() === region || n.region_label.toLowerCase() === region;

type Hit = { region: string; region_label: string };

/** Up to 20 picker hits for `q`, searching with `search(text, limit)`. */
export async function pickerHits<T extends Hit>(q: string, search: (text: string, limit: number) => Promise<T[]>): Promise<T[]> {
  const { q: text, region } = nodeQuery(q);
  if (region !== null) {
    const kept = (await search(text, 100)).filter((n) => inRegion(n, region));
    if (kept.length) return kept.slice(0, 20);
  }
  return search(q, 20);
}
