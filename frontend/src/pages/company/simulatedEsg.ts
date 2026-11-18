import type { SimulatedObservation } from "../../types";

export interface SimulatedEsgView {
  /** `<letter> <label>`, e.g. `B Credible`. */
  grade: string | null;
  peerGroup: string | null;
  /** The seven climate values, then the eight controversial revenue shares, in the API's (schema) order. */
  rows: { fieldId: string; label: string; value: string }[];
}

const NUMBER = new Intl.NumberFormat("en", { maximumFractionDigits: 2 });
/** The eight controversial activity shares, not the green ones (`climate_green_revenue_pct`, `green_revenue_pct`). */
const isShare = (fieldId: string) => fieldId.endsWith("_revenue_pct") && !fieldId.includes("green");

/** What a Simulated ESG panel shows of a company's simulated observations; null when it has none.
 * Revenue shares are fractions in the data and percent on screen. */
export function simulatedEsgView(obs: SimulatedObservation[]): SimulatedEsgView | null {
  if (!obs.length) return null;
  const by = new Map(obs.map((o) => [o.field_id, o.value]));
  const letter = by.get("transition_grade");
  const rows = obs
    .filter((o) => o.field_id.startsWith("climate_") || isShare(o.field_id))
    .map((o) => ({
      fieldId: o.field_id,
      label: o.field_name,
      value: typeof o.value !== "number" ? String(o.value ?? "—")
        : isShare(o.field_id) ? `${NUMBER.format(o.value * 100)}%`
        : `${NUMBER.format(o.value)}${o.unit === "%" ? "%" : o.unit ? ` ${o.unit}` : ""}`,
    }));
  return {
    grade: letter == null ? null : [letter, by.get("transition_grade_label")].filter((x) => x != null).join(" "),
    peerGroup: by.has("peer_group") ? String(by.get("peer_group")) : null,
    rows,
  };
}
