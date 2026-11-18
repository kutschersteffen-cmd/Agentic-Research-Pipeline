// Ask the Portfolio: what the page sends from the pane's selection, and how it shows the dates of an answer.

export interface TrendPointLike {
  as_of: string;
  result: {
    total_market_value_eur: number;
    rows: { group_value: string; market_value_eur?: number | null; weighted_avg_value?: number | null; holding_count: number }[];
  };
}

/** The request body: the typed question as it is, plus the pane's selection. A date that is not set is left out. */
export function askBody(question: string, portfolioIds: string[], asOf: string | undefined, dateRange: [string, string] | null) {
  return {
    question,
    portfolio_ids: portfolioIds,
    ...(dateRange ? { date_range: dateRange } : asOf ? { as_of: asOf } : {}),
  };
}

/** Set when both trend dates are given and the end is before the start; the selection then counts as "latest". */
export function trendRangeError(from: string, to: string): string | null {
  return from && to && to < from ? "The end date is before the start date." : null;
}

export function snapshotLine(dates: string[]): string | null {
  if (dates.length === 0) return null;
  return `${dates.length === 1 ? "Snapshot used" : "Snapshots used"}: ${dates.join(", ")}`;
}

export function formatEur(value: number, scale: string = "units"): string {
  return scale === "millions"
    ? (value / 1e6).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : value.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

/** A trend as a table: one row per date, one column per group (in order of first appearance), "—" where a
 * group has no row on that date, and a Total column for market values. */
export function trendTable(trend: TrendPointLike[], metric: string, scale: string = "units"): { headers: string[]; rows: string[][] } {
  const groups: string[] = [];
  for (const p of trend) for (const r of p.result.rows) if (!groups.includes(r.group_value)) groups.push(r.group_value);
  const money = metric === "market_value_sum";
  const cell = (r: TrendPointLike["result"]["rows"][number] | undefined): string => {
    if (!r) return "—";
    if (money) return r.market_value_eur != null ? formatEur(r.market_value_eur, scale) : "--";
    if (metric === "count") return String(r.holding_count);
    return r.weighted_avg_value != null ? r.weighted_avg_value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : "no data";
  };
  return {
    headers: ["As of", ...groups, ...(money ? ["Total"] : [])],
    rows: [...trend]
      .sort((a, b) => a.as_of.localeCompare(b.as_of))
      .map((p) => [
        p.as_of,
        ...groups.map((g) => cell(p.result.rows.find((r) => r.group_value === g))),
        ...(money ? [formatEur(p.result.total_market_value_eur, scale)] : []),
      ]),
  };
}

const DIMENSION_LABELS: Record<string, string> = {
  portfolio_id: "Portfolio",
  asset_class: "Asset class",
  company_id: "Company",
  company_name: "Company",
  sector: "Sector",
  country: "Country",
  currency: "Currency",
  gics_sector: "GICS sector",
  gics_industry_group: "GICS industry group",
  gics_industry: "GICS industry",
  gics_sub_industry: "GICS sub-industry",
};

/** A grouping dimension as a person reads it; an id this list does not know gets spaces and a capital first letter. */
export function dimensionLabel(id: string): string {
  const spaced = id.replace(/_/g, " ");
  return DIMENSION_LABELS[id] ?? spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Column headers of the point-in-time table's value column. */
export function valueHeader(metric: string, scale: string = "units", unit: string = ""): string {
  if (metric === "weighted_avg_datapoint") return unit ? `Weighted avg (${unit})` : "Weighted avg";
  return scale === "millions" ? "Market value (EUR million)" : "Market value (EUR)";
}

/** "EUR 1,234" or "EUR 1.23 million". */
export function eurText(value: number, scale: string = "units"): string {
  return `EUR ${formatEur(value, scale)}${scale === "millions" ? " million" : ""}`;
}
