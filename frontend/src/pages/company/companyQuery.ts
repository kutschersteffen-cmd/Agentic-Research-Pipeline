import type { CompanyFactStatus, FactCitation, FactTrail, FactVersion } from "../../types";

export const STATUS_TEXT: Record<CompanyFactStatus, string> = {
  auto_accepted: "auto-accepted",
  approved: "approved",
  edited: "edited",
  pending_review: "awaiting review",
  held: "held",
};

export interface FactFilters {
  /** `<input type="date">` value, YYYY-MM-DD. */
  asOf?: string;
  kind?: string;
  fieldId?: string;
  periodEnd?: string;
  limit?: number;
}

/** A company ref (UUID or `SCHEME:value`) as one URL path segment. */
export const encodeRef = (ref: string): string => encodeURIComponent(ref);

/** The company page for a universe company id. */
export const companyHref = (companyId: string): string => `#/companies/${encodeRef(`UNIVERSE:${companyId}`)}`;

/** The last millisecond of a YYYY-MM-DD day in the viewer's time zone, as ISO UTC. */
function endOfLocalDay(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d, 23, 59, 59, 999).toISOString();
}

/** GET path for a company's facts; empty filters are left out. An as-of date
 * means "as the data stood at the end of that day" where the viewer is. */
export function factsUrl(ref: string, f: FactFilters): string {
  const pairs: [string, string | undefined][] = [
    ["as_of", f.asOf ? endOfLocalDay(f.asOf) : undefined],
    ["kind", f.kind],
    ["field_id", f.fieldId],
    ["period_end", f.periodEnd],
    ["limit", f.limit?.toString()],
  ];
  const qs = new URLSearchParams(pairs.filter((p): p is [string, string] => !!p[1])).toString();
  return `/api/companies/${encodeRef(ref)}/facts${qs ? `?${qs}` : ""}`;
}

/** Where one version of a fact came from: the primary cited document and page,
 * else the provider and its load date, else the run (mirrors the facts list's source_label). */
export function sourceLabel(v: FactVersion): string {
  const c = v.citations.find((x) => x.role === "primary") ?? v.citations[0];
  if (c) return c.page != null ? `${c.title} p.${c.page}` : c.title;
  if (v.load) return `${v.load.source_name} · ${v.load.fetched_at.slice(0, 10)}`;
  return v.observation.run_id ?? v.observation.source_kind;
}

/** The primary citation of a fact's current version, or null when it has none. */
export function primaryCitation(trail: FactTrail): FactCitation | null {
  return trail.versions.find((v) => v.valid_to === null)?.citations.find((c) => c.role === "primary") ?? null;
}

/** At most two decimals, rounded half up, trailing zeros dropped (backend `fmt_number`); shifting
 * by exponent strings avoids binary-float ties such as 1.005 * 100 = 100.49999. */
export const fmtNumber = (v: number): string => String(Number(Math.round(Number(v + "e2")) + "e-2"));
