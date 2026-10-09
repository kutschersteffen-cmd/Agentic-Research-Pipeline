import type { XbrlMarket } from "../types";
export type SortState = { key: string; order: "asc" | "desc" };

export const toggleTag = (selected: string[], tagId: string): string[] =>
  selected.includes(tagId) ? selected.filter((t) => t !== tagId) : [...new Set([...selected, tagId])];

/** Query string for GET /api/xbrl/tags, with the leading "?"; "" when nothing is set. */
export function tagQuery(p: {
  q?: string;
  taxonomy?: string;
  seenOnly?: boolean;
  extensionOnly?: boolean;
  offset?: number;
  limit?: number;
}): string {
  const pairs: [string, string | undefined][] = [
    ["q", p.q || undefined],
    ["taxonomy", p.taxonomy || undefined],
    ["seen_only", p.seenOnly ? "true" : undefined],
    ["extension_only", p.extensionOnly ? "true" : undefined],
    ["offset", p.offset?.toString()],
    ["limit", p.limit?.toString()],
  ];
  const parts = pairs.filter(([, v]) => v !== undefined).map(([k, v]) => `${k}=${encodeURIComponent(v as string)}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

const STATUS: Record<string, string> = {
  ok: "Facts fetched",
  unchanged: "Already up to date",
  no_cik: "No SEC CIK for this company",
  no_lei: "No LEI in the universe row",
  not_found: "Not found at the SEC",
  error: "Failed",
};
const REPORT: Record<string, string> = {
  stored: "Annual report saved",
  unchanged: "Annual report already saved",
  none: "No annual report found",
  error: "Annual report download failed",
};
/** What identifies a company in each market: the SEC CIK, or the ESEF LEI. */
export const keyLabel = (market: XbrlMarket): "CIK" | "LEI" => (market === "esef" ? "LEI" : "CIK");
/** A third-party URL is only linked when it is http(s): never javascript: or data:. */
export const safeHref = (url: string | null | undefined): string | null => (url && /^https?:\/\//i.test(url) ? url : null);
export const statusText = (status: string): string => STATUS[status] ?? status;
export const reportText = (report: string): string => REPORT[report] ?? report;

export function verifySummary(rows: { outcome: string }[]): Record<string, number> {
  const out: Record<string, number> = { match: 0, mismatch: 0, missing_in_run: 0, missing_in_xbrl: 0 };
  for (const r of rows) out[r.outcome] = (out[r.outcome] ?? 0) + 1;
  return out;
}

export const formatFactValue = (value: number, _unit: string): string =>
  value.toLocaleString("en-US", { maximumFractionDigits: 4 });

export const periodLabel = (start: string | null, end: string): string =>
  start ? `${start} to ${end}` : `as of ${end}`;

export const secFilingUrl = (cik: string, accession: string): string =>
  `https://www.sec.gov/Archives/edgar/data/${cik.replace(/^0+/, "")}/${accession.replaceAll("-", "")}/`;

export const nextSort = (current: SortState, key: string): SortState =>
  current.key === key ? { key, order: current.order === "asc" ? "desc" : "asc" } : { key, order: "asc" };

export const ariaSort = (current: SortState, key: string): "ascending" | "descending" | "none" =>
  current.key !== key ? "none" : current.order === "asc" ? "ascending" : "descending";

export const TAXONOMIES = ["us-gaap", "ifrs-full", "dei", "esrs"];

const n = (x: number) => x.toLocaleString("en-US");
/** A pager's visible range, e.g. "21–40 of 1,234"; "0 of 0" when empty. */
export const rangeLabel = (offset: number, count: number, total: number): string =>
  count ? `${n(offset + 1)}–${n(offset + count)} of ${n(total)}` : `0 of ${n(total)}`;

/** Tolerance as typed (a percentage, "0.5"): the fraction the API takes, or null unless it is a number from 0 to 100. */
export function toleranceFraction(percent: string): number | null {
  const t = percent.trim().replace(",", ".");
  if (!/^\d+(\.\d+)?$/.test(t)) return null;
  const p = Number(t);
  return p <= 100 ? Number((p / 100).toPrecision(12)) : null;
}

/** The API's mapping (metric to the run's field id); null until at least one field id is given. */
export function verifyMapping(revenueField: string, capexField: string): Record<string, string> | null {
  const m: Record<string, string> = {};
  if (revenueField.trim()) m.revenue = revenueField.trim();
  if (capexField.trim()) m.capex = capexField.trim();
  return Object.keys(m).length ? m : null;
}

const OUTCOME_ORDER = ["mismatch", "missing_in_run", "missing_in_xbrl", "match"];
/** Verify rows with the ones needing a look first (mismatches, then missing), then by company, metric and year. */
export function sortVerifyRows<T extends { outcome: string; company_id: string; metric: string; fiscal_year: number }>(rows: T[]): T[] {
  const rank = (o: string) => OUTCOME_ORDER.indexOf(o);
  return [...rows].sort(
    (a, b) =>
      rank(a.outcome) - rank(b.outcome) ||
      a.company_id.localeCompare(b.company_id) ||
      a.metric.localeCompare(b.metric) ||
      a.fiscal_year - b.fiscal_year,
  );
}

export const OUTCOME_TEXT: Record<string, string> = {
  match: "Match",
  mismatch: "Mismatch",
  missing_in_run: "Missing in run",
  missing_in_xbrl: "Missing in XBRL",
};
export const outcomeText = (o: string): string => OUTCOME_TEXT[o] ?? o;
export const metricText = (m: string): string => (m === "revenue" ? "Revenue" : m === "capex" ? "Capex" : m);
export const verifyDetailText = (d: string): string => (d === "unit" ? "Units differ" : d || "–");

/** A fetch run is fully done when it completed, nothing failed and every company was reached. */
export const fetchRunDone = (m: { status: string; failed_count: number; completed_count: number; company_count: number }): boolean =>
  m.status === "completed" && m.failed_count === 0 && m.completed_count + m.failed_count >= m.company_count;

/** Retry is offered when the run is not in progress (or polling stalled) and it is not fully done. */
export const canRetryFetch = (
  m: { status: string; failed_count: number; completed_count: number; company_count: number } | null,
  stalled: boolean,
): boolean => m !== null && (stalled || (m.status !== "pending" && m.status !== "running")) && !fetchRunDone(m);
