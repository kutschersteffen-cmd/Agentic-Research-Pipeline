import type { MechanismConfig } from "../types";

/** Evenly spaced tier boundaries on the scale, best tier first (the engine reads cuts high to low). */
export function evenCuts(min: number, max: number, tiers: number): number[] {
  const step = (max - min) / tiers;
  return Array.from({ length: Math.max(0, tiers - 1) }, (_, i) => Math.round((max - step * (i + 1)) * 100) / 100);
}

/** The framework switched into levels mode: a 1–7 scale, fixed cut-points on it, and one cluster to start from. */
export function toLevelsMode(config: MechanismConfig): MechanismConfig {
  const levelMin = config.level_min ?? 1;
  const levelMax = config.level_max ?? 7;
  const dimensions = config.dimensions.length ? config.dimensions : [{ id: "c1", name: "Cluster 1", weight: 1, derived_from: [] }];
  return {
    ...config,
    mode: "levels",
    level_min: levelMin,
    level_max: levelMax,
    level_criteria: config.level_criteria ?? [],
    dimensions,
    cut_mode: "absolute",
    pinned_cuts: evenCuts(levelMin, levelMax, config.tiers.length),
  };
}
