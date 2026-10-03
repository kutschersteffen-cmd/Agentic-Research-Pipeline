import type { BIDesignResult } from "../types";

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
