import type { ExtractedField } from "../types";

/** What a field's value reads as: the state wins over the raw value; legacy fields have no state. */
export function valueLabel(f: Pick<ExtractedField, "value" | "value_state" | "unit">): string {
  const withUnit = (v: string) => (f.unit ? `${v} ${f.unit}` : v);
  switch (f.value_state) {
    case "not_found": return "not disclosed";
    case "not_applicable": return "not applicable";
    case "zero": return withUnit("0");
    case "found": return withUnit(String(f.value));
    default: return f.value == null ? "not disclosed" : String(f.value);
  }
}

/** A schema may run for real only when flagged released and no field is still draft or retired. */
export const isReleased = (s: { release_flag?: boolean; fields: { status?: string }[] }): boolean =>
  !!s.release_flag && s.fields.every((f) => f.status === "released");
