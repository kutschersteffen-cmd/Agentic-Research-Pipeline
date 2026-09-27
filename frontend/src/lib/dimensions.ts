import type { MechanismConfig } from "../types";

/** A dimension of its own for one criterion -- the neutral default when a
 * criterion is added by hand, since grouping it with unrelated criteria
 * would share their weight. Derived ids are d0, d1, …; this continues them. */
export function newDimension(config: MechanismConfig, column: string): MechanismConfig["dimensions"][number] {
  const taken = new Set(config.dimensions.map((d) => d.id));
  let n = config.dimensions.length;
  while (taken.has(`d${n}`)) n += 1;
  return { id: `d${n}`, name: column.replace(/_/g, " "), weight: 1, derived_from: [] };
}
