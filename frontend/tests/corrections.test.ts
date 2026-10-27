import test from "node:test";
import assert from "node:assert/strict";
import { correctionLine, recordFieldNames } from "../src/lib/corrections.ts";
import type { Correction } from "../src/types.ts";

const names: Record<string, string> = { tc_capex_total: "Total capex", tc_capex_total_planned: "Total capex, planned" };
const name = (id: string) => names[id] ?? id;
const c = (o: Partial<Correction>) => ({ attribute: "value", original: null, corrected: null, reason: "", ...o }) as Correction;

test("unit_scale line", () => {
  assert.equal(
    correctionLine(c({ rule: "unit_scale", attribute: "unit", original: "USD millions", corrected: "USD billions", reason: 'The quote says "billion" next to 2.794.' }), name),
    'Auto-corrected (Unit scale): USD millions → USD billions. The quote says "billion" next to 2.794.',
  );
});

test("label_map line", () => {
  assert.equal(
    correctionLine(c({ rule: "label_map", original: "cash-flow capex", corrected: "cash_flow", reason: '"cash-flow capex" maps to the allowed value "cash_flow".' }), name),
    'Auto-corrected (Label): cash-flow capex → cash_flow. "cash-flow capex" maps to the allowed value "cash_flow".',
  );
});

test("period_fill line shows an empty original as a dash", () => {
  assert.equal(
    correctionLine(c({ rule: "period_fill", attribute: "period_end", corrected: "2025-12-31", reason: "The quote names only 2025." }), name),
    "Auto-corrected (Year): — → 2025-12-31. The quote names only 2025.",
  );
});

test("planned_move line shows field names, not IDs", () => {
  assert.equal(
    correctionLine(c({ rule: "planned_move", attribute: "field_id", original: "tc_capex_total", corrected: "tc_capex_total_planned", reason: "Period 2026-12-31 is after the report's period end 2025-12-31, so it is a planned figure." }), name),
    "Auto-corrected (Planned figure): Total capex → Total capex, planned. Period 2026-12-31 is after the report's period end 2025-12-31, so it is a planned figure.",
  );
});

test("planned_move on a cleared row shows the number and a dash, no name lookup", () => {
  assert.equal(
    correctionLine(c({ rule: "planned_move", original: 3, corrected: null, reason: "Moved to the planned field." }), name),
    "Auto-corrected (Planned figure): 3 → —. Moved to the planned field.",
  );
});

test("a moved row's original field is named from the schema when the record has no row for it", () => {
  const moved = { field_id: "tc_capex_total_planned", field_name: "Total capex, planned" };
  const record = { fields: [moved], field_names: names } as never;
  const fieldNames = recordFieldNames(record);
  assert.equal(
    correctionLine(c({ rule: "planned_move", attribute: "field_id", original: "tc_capex_total", corrected: "tc_capex_total_planned", reason: "r." }), (id) => fieldNames[id] ?? id),
    "Auto-corrected (Planned figure): Total capex → Total capex, planned. r.",
  );
  assert.equal(recordFieldNames({ fields: [moved] } as never).tc_capex_total, undefined);
});
