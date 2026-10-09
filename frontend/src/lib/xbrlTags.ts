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
  not_found: "Not found at the SEC",
  error: "Failed",
};
const REPORT: Record<string, string> = {
  stored: "Annual report saved",
  unchanged: "Annual report already saved",
  none: "No annual report found",
  error: "Annual report download failed",
};
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
