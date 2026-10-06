/** Sample data and pure scoring for the rank-range ladder. */

export interface Criterion {
  name: string;
  /** true when the direction (higher is better or worse) was inferred, not stated. */
  inferred: boolean;
}

export const CRITERIA: Criterion[] = [
  { name: "Emissions intensity", inferred: false },
  { name: "Transition plan", inferred: false },
  { name: "Disclosure quality", inferred: false },
  { name: "Supply-chain exposure", inferred: true },
  { name: "Peer momentum", inferred: true },
];

/** Four specifications: which criteria each one scores with (1 = used). */
export const SPECS: number[][] = [
  [1, 1, 1, 0, 0],
  [1, 1, 1, 1, 0],
  [1, 1, 1, 0, 1],
  [1, 1, 1, 1, 1],
];

export const NAMES = [
  "Alder Marine", "Borealis Steel", "Cobalt Grid", "Dunmore Foods", "Estuary Power",
  "Fennel Chem", "Garnet Mining", "Halcyon Air", "Ironbark Cement", "Juniper Rail",
  "Kestrel Oil", "Lumen Retail", "Meridian Pulp", "Northwind Gas", "Orchard Agri",
  "Pelican Freight", "Quarry Lane", "Redwood Paper", "Sable Shipping", "Tidewater Utility",
  "Umber Glass", "Vantage Auto", "Willow Textile", "Yarrow Fertiliser", "Zephyr Aviation",
];

/** Last rank of each tier, in order. */
export const TIER_ENDS = [5, 12, 19, NAMES.length];
export const TIER_NAMES = ["T1 engage", "T2 prioritise", "T3 monitor", "T4 park"];
export const DEFAULT_WEIGHTS = [3, 3, 2, 2, 2];

export const tierOf = (rank: number): number => TIER_ENDS.findIndex((end) => rank <= end);

/** Deterministic sample criterion values in 0..1, one row per entity. */
export function sampleValues(seed = 7): number[][] {
  let s = seed;
  const rnd = () => (s = (s * 1103515245 + 12345) % 2147483648) / 2147483648;
  return NAMES.map(() => {
    const base = rnd();
    return CRITERIA.map(() => Math.min(1, Math.max(0, 0.55 * base + 0.45 * rnd())));
  });
}

export interface Entity {
  index: number;
  lo: number;
  hi: number;
  /** straddles a tier boundary across specifications */
  unstable: boolean;
  /** the low / high edge is set only by specs that use an inferred direction */
  hatchLo: boolean;
  hatchHi: boolean;
}

/** Rank (1 = best) of every entity under one specification; ties break by index. */
function ranksFor(values: number[][], weights: number[], spec: number[]): number[] {
  const score = values.map((v) => v.reduce((a, x, c) => a + x * weights[c] * spec[c], 0));
  const order = score.map((_, i) => i).sort((a, b) => score[b] - score[a] || a - b);
  const ranks: number[] = [];
  order.forEach((e, k) => (ranks[e] = k + 1));
  return ranks;
}

/** Rank range of every entity across all specs, returned best-first (by range midpoint). */
export function rankRanges(values: number[][], weights: number[], specs: number[][] = SPECS): Entity[] {
  const perSpec = specs.map((spec) => ranksFor(values, weights, spec));
  const usesInferred = (k: number) => specs[k].some((m, c) => m && CRITERIA[c].inferred);
  const entities = values.map((_, i): Entity => {
    const rs = perSpec.map((r) => r[i]);
    const lo = Math.min(...rs);
    const hi = Math.max(...rs);
    const setBy = (edge: number) => rs.flatMap((x, k) => (x === edge ? [k] : []));
    return {
      index: i,
      lo,
      hi,
      unstable: tierOf(lo) !== tierOf(hi),
      hatchLo: lo !== hi && setBy(lo).every(usesInferred),
      hatchHi: lo !== hi && setBy(hi).every(usesInferred),
    };
  });
  return entities.sort((a, b) => a.lo + a.hi - (b.lo + b.hi) || a.lo - b.lo || a.index - b.index);
}
