// Theme position and standards (dossier step 5) display rules: version states, criteria and the check grid.
// The rules themselves are enforced by the backend (arp/themes/position.py).
import type { PositionView, Standard, StandardsCheck, StandardsDraft, StandardsVersion, StandardsView } from "../types.ts";

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

/** Field ids the active version's activation released (it releases that version's whole theme schema). */
export const releasedFieldIds = (view: Pick<StandardsView, "versions" | "active_version">) =>
  new Set((view.versions.find((v) => v.version === view.active_version)?.schema?.fields ?? []).map((f) => f.field_id));

/** What the editor starts from: the version's standards and the fields it adds. A field released since the version
 * was saved is existing data now, so saving it unchanged does not fail with "use data existing". */
export function editorDraft(version: StandardsVersion, released: Set<string>): StandardsDraft {
  const standards = version.standards.map((s) => (s.data === "new" && released.has(s.field_id) ? { ...s, data: "existing" as const } : s));
  const added = new Set(standards.filter((s) => s.data === "new").map((s) => s.field_id));
  return { standards, new_fields: (version.schema?.fields ?? []).filter((f) => added.has(f.field_id)) };
}
