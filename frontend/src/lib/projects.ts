import type { BIChartPlan, BIDesignResult, DashboardItem, OpenedDashboard, OpenResult } from "../types";
import { pickDefaultDashboard } from "./biEmbed.ts";

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
  onCreated?: (id: string) => void,
): Promise<{ id: string; result: OpenResult }> {
  const { id } = await api.createProject({ name: input.name, description: "" });
  onCreated?.(id);
  for (const f of input.files) await api.uploadProjectData(id, f, input.notionalEur);
  return { id, result: await api.openProject(id) };
}

/** Body for POST /api/projects/{id}/dashboards from a designer result, or null if it carries no plan. */
export function saveBody(r: BIDesignResult | null): { title: string; plan: BIChartPlan } | null {
  return r?.dashboard_id != null && r.plan ? { title: r.plan.title, plan: r.plan } : null;
}

/** Dashboards the picker can embed (a skipped one has no Superset id). */
export const embeddable = (ds: OpenedDashboard[]) =>
  ds.filter((d): d is OpenedDashboard & { id: number } => d.id !== null);

/** FastAPI's 422 body: `detail` is a list of {loc, msg} objects (pydantic) or of plain strings
 * (the plan validator's problems). Rendered as "spec › screens: msg" / "problem; problem". */
export function formatValidationErrors(errors: ({ loc?: (string | number)[]; msg?: string } | string)[]): string {
  return errors
    .map((e) => {
      if (typeof e === "string") return e;
      const where = (e.loc ?? []).filter((part) => part !== "body").join(" › ");
      const msg = (e.msg ?? "invalid").replace(/^Value error, /, "");
      return where ? `${where}: ${msg}` : msg;
    })
    .join("; ");
}

/** Picker contents in project mode: the project's own dashboards, then every other `arp-` dashboard. */
export function projectGroups(project: string, mine: DashboardItem[], all: DashboardItem[] | null) {
  const own = new Set(mine.map((d) => d.id));
  const others = (all ?? []).filter((d) => !d.slug.startsWith(`arp-${project}--`) && !own.has(d.id));
  return { mine, others, union: [...mine, ...others] };
}

/** Only a hand-built dashboard from the second group can be saved (exported) into the project. */
export const isOther = (others: DashboardItem[], id: number | null) => others.some((d) => d.id === id);

/** Picker state. `standard` is the list of all `arp-` dashboards; the project fields only matter once a project is chosen. */
export interface PickerState {
  standard: DashboardItem[] | null;
  project: string | null;
  projectDashboards: DashboardItem[] | null;
  selectedId: number | null;
}
export type PickerEvent =
  | { type: "select"; project: string | null } // the selector changed (also create, once the id is known)
  | { type: "opened"; dashboards: OpenedDashboard[] } // an open finished (or failed: [])
  | { type: "list"; items: DashboardItem[]; preferId?: number } // the standard list (re)loaded
  | { type: "saved"; item: DashboardItem } // a dashboard was added to the project
  | { type: "pick"; id: number }; // the person picked a dashboard

export const initialPicker: PickerState = { standard: null, project: null, projectDashboards: null, selectedId: null };

export function reducePicker(s: PickerState, e: PickerEvent): PickerState {
  switch (e.type) {
    case "select":
      return {
        ...s,
        project: e.project,
        projectDashboards: null,
        selectedId: e.project ? s.selectedId : (s.standard ? pickDefaultDashboard(s.standard)?.id ?? null : null),
      };
    case "opened": {
      if (s.project === null) return s; // a late or failed open must not touch Standard mode
      const items = embeddable(e.dashboards).map(({ id, slug, title, published }) => ({ id, slug, title, published }));
      return { ...s, projectDashboards: items, selectedId: items[0]?.id ?? null };
    }
    case "list": {
      if (s.project !== null) return { ...s, standard: e.items }; // the project's selection is not ours to move
      const listed = (id: number | null | undefined) => e.items.some((d) => d.id === id);
      const selectedId = listed(e.preferId) ? e.preferId! : listed(s.selectedId) ? s.selectedId : pickDefaultDashboard(e.items)?.id ?? null;
      return { ...s, standard: e.items, selectedId };
    }
    case "pick":
      return { ...s, selectedId: e.id };
    case "saved":
      return { ...s, projectDashboards: [...(s.projectDashboards ?? []).filter((d) => d.id !== e.item.id), e.item], selectedId: e.item.id };
  }
}

/** One readable line for an open's data summaries ({notional_eur, portfolios: [{holdings_written, weight_sum}]} each):
 * "4 funds, 2,829 holdings, EUR 400.6M". Notional is per file; a fund's share is notional x weight_sum
 * (1 when the summary lacks it). */
export function dataLine(data: Record<string, unknown>[]): string {
  let funds = 0, holdings = 0, eur = 0;
  for (const d of data) {
    const ps = Array.isArray(d.portfolios) ? (d.portfolios as Record<string, unknown>[]) : [];
    funds += ps.length;
    for (const p of ps) {
      holdings += Number(p?.holdings_written) || 0;
      eur += (Number(d.notional_eur) || 0) * (p?.weight_sum != null && Number.isFinite(Number(p.weight_sum)) ? Number(p.weight_sum) : 1);
    }
  }
  if (funds === 0) return "Data loaded";
  const n = (k: number, w: string) => `${k.toLocaleString("en-US")} ${w}${k === 1 ? "" : "s"}`;
  const parts = [n(funds, "fund"), n(holdings, "holding")];
  if (eur >= 1e6) parts.push(`EUR ${(eur / 1e6).toFixed(1)}M`);
  else if (eur >= 1e3) parts.push(`EUR ${Math.round(eur / 1e3)}k`);
  else if (eur > 0) parts.push(`EUR ${Math.round(eur)}`);
  return parts.join(", ");
}
