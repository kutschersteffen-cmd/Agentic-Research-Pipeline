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

/** The field as a reviewer's edit leaves it; mirrors the backend rule: state follows the value, canonical and FX no longer apply. */
export const withEditedValue = (f: ExtractedField, edited: string): ExtractedField => ({
  ...f,
  value: edited,
  value_state: Number(edited) === 0 && edited.trim() !== "" ? "zero" : "found",
  canonical_value: null,
  canonical_unit: null,
  fx_rate: null,
});
