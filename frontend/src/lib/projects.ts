import type { BIDesignResult, OpenedDashboard, OpenResult } from "../types";

export const STANDARD = "";
export const DEFAULT_NOTIONAL_EUR = 100_000_000;
export const UNSCOPED_CAVEAT = "Hand-built dashboards are not limited to this project's data";

/** The slice of `api` the project flows use; tests pass a stub. */
export interface ProjectFlowApi {
  createProject(body: { name: string; description: string }): Promise<{ id: string }>;
  uploadProjectData(id: string, file: File, notionalEur: number): Promise<unknown>;
  openProject(id: string): Promise<OpenResult>;
}

/** Our API's message without the "502: " status prefix. Never a raw body: `request` only ever
 * throws our own `detail` text (or a status line). */
export const apiMessage = (e: unknown): string =>
  (e instanceof Error ? e.message : String(e)).replace(/^\d{3}:\s*/, "");

/** create -> upload (once per file, in order) -> open. */
export async function createAndOpen(
  api: ProjectFlowApi,
  input: { name: string; notionalEur: number; files: File[] },
): Promise<{ id: string; result: OpenResult }> {
  const { id } = await api.createProject({ name: input.name, description: "" });
  for (const f of input.files) await api.uploadProjectData(id, f, input.notionalEur);
  return { id, result: await api.openProject(id) };
}

/** Body for POST /api/projects/{id}/dashboards from a designer result, or null if it carries no plan. */
export function saveBody(r: BIDesignResult | null): { title: string; plan: NonNullable<BIDesignResult["plan"]> } | null {
  return r?.dashboard_id != null && r.plan ? { title: r.plan.title, plan: r.plan } : null;
}

/** Dashboards the picker can embed (a skipped one has no Superset id). */
export const embeddable = (ds: OpenedDashboard[]) =>
  ds.filter((d): d is OpenedDashboard & { id: number } => d.id !== null);
