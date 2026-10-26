// Theme position and standards (dossier step 5) display rules: version states, criteria and the check grid.
// The rules themselves are enforced by the backend (arp/themes/position.py).
import type { PositionView, Standard, StandardsCheck, StandardsVersion } from "../types.ts";

/** `Approved by <id>` when the version is the approved one, else who drafted it. */
export function positionState(view: Pick<PositionView, "approvals" | "approved_version">, v: { version: number; created_by: string }): string {
  if (view.approved_version === v.version) {
    const row = [...view.approvals].reverse().find((a) => a.version === v.version);
    return `Approved by ${row?.approved_by ?? "?"}`;
  }
  return `Draft by ${v.created_by}`;
}

export const criterion = (s: Pick<Standard, "field_id" | "operator" | "value">, names: Record<string, string>) =>
  `${names[s.field_id] ?? s.field_id} ${s.operator} ${JSON.stringify(s.value)}`;

export const DATA_LABEL: Record<Standard["data"], string> = { existing: "Existing field", new: "New field" };

export const RESULT_LABEL: Record<string, string> = { met: "Met", unmet: "Unmet", no_data: "No data" };

/** Companies (in result order) by standard ids, each cell the result label. */
export function checkGrid(check: StandardsCheck): { standards: string[]; rows: { name: string; cells: string[] }[] } {
  const standards = [...new Set(check.results.map((r) => r.standard_id))];
  const byCompany = new Map<string, { name: string; cells: Record<string, string> }>();
  for (const r of check.results) {
    const row = byCompany.get(r.company_id) ?? { name: r.name, cells: {} };
    row.cells[r.standard_id] = RESULT_LABEL[r.result] ?? r.result;
    byCompany.set(r.company_id, row);
  }
  return { standards, rows: [...byCompany.values()].map((r) => ({ name: r.name, cells: standards.map((s) => r.cells[s] ?? "") })) };
}

/** The latest saved version above 0, if any. */
export const latestStandards = (versions: StandardsVersion[]) => versions.filter((v) => v.version > 0).at(-1) ?? null;
