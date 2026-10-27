import type { Correction, ExtractionRecord } from "../types";

const LABELS: Record<Correction["rule"], string> = {
  label_map: "Label", period_fill: "Year", unit_scale: "Unit scale", planned_move: "Planned figure",
};

/** One reviewer line per correction. A moved row's original and corrected are field IDs, shown as names. */
export function correctionLine(c: Correction, fieldName: (id: string) => string): string {
  const show = (v: Correction["original"]) =>
    v == null ? "—" : c.attribute === "field_id" ? fieldName(String(v)) : String(v);
  return `Auto-corrected (${LABELS[c.rule]}): ${show(c.original)} → ${show(c.corrected)}. ${c.reason}`;
}

/** The record's field names for correction lines: the schema's, with its own rows' names as a fallback. */
export const recordFieldNames = (r: Pick<ExtractionRecord, "fields" | "field_names">): Record<string, string> => ({
  ...Object.fromEntries(r.fields.map((f) => [f.field_id, f.field_name])),
  ...r.field_names,
});
