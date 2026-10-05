import type { BIDesignResult, DashboardItem } from "../types";

// `env` is undefined under `node --test`, hence the `?.`.
export const SUPERSET_URL: string = import.meta.env?.VITE_SUPERSET_URL ?? "http://127.0.0.1:8088";

export function designRequestBody(brief: string): { brief: string } {
  return { brief: brief.trim() };
}

/** The iframe url the embed SDK loads. It names the dashboard's embedded UUID
 * (from /api/bi/embed-token), not its numeric id; null while there is nothing to embed. */
export function embedUrlFor(
  result: Pick<BIDesignResult, "dashboard_id">,
  embeddedId: string | null,
  supersetDomain: string = SUPERSET_URL,
): string | null {
  if (result.dashboard_id === null || !embeddedId) return null;
  return `${supersetDomain.replace(/\/+$/, "")}/embedded/${embeddedId}`;
}

/** The dashboard the tab opens on: the preferred slug if listed, else the first, else none. */
export function pickDefaultDashboard(items: DashboardItem[], preferredSlug = "arp-risk-exposure"): DashboardItem | null {
  return items.find((d) => d.slug === preferredSlug) ?? items[0] ?? null;
}

/** The embed error for people: a dashboard that vanished or lost its `arp-` slug (403/404)
 * is "no longer available"; anything else loses its "NNN: " status prefix. */
export function embedErrorText(error: string): string {
  if (/^40[34]:/.test(error)) return "This dashboard is no longer available here.";
  return error.replace(/^\d{3}:\s*/, "");
}

/** What the Company Profile adds to the embed-token request. The server checks the id
 * against the store and builds the guest token's RLS clause from it; the client never writes SQL. */
export function profileEmbedParams(companyId: string | null): { company_id?: string } {
  return companyId ? { company_id: companyId } : {};
}
