import { useState } from "react";
import type { AggregationResult, TrendPoint } from "../types";
import { AggregationResultTable } from "./AggregationResultTable";
import { BarChart } from "./BarChart";
import { LineChart, type LineSeries } from "./LineChart";
import { TrendTable } from "./TrendTable";

function formatterFor(result: AggregationResult, unit?: string) {
  if (result.metric === "weighted_avg_datapoint") {
    return (v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 2 }) + (unit ? ` ${unit}` : "");
  }
  if (result.metric === "count") {
    return (v: number) => v.toLocaleString();
  }
  return (v: number) => `EUR ${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

/** Table/chart toggle for one point-in-time AggregationResult -- a bar
 * chart of the same rows the table already shows, nothing hidden behind
 * the chart view that the table doesn't also carry. */
export function AggregationView({ result, unit }: { result: AggregationResult; unit?: string }) {
  const [view, setView] = useState<"table" | "chart">("table");
  const valueKey = result.metric === "weighted_avg_datapoint" ? "weighted_avg_value" : result.metric === "count" ? "holding_count" : "market_value_eur";
  const data = result.rows.map((r) => ({ label: r.group_value, value: (r[valueKey] as number | null | undefined) ?? 0 }));

  return (
    <div>
      <div className="view-toggle">
        <button className={view === "table" ? "active" : ""} onClick={() => setView("table")}>
          Table
        </button>
        <button className={view === "chart" ? "active" : ""} onClick={() => setView("chart")}>
          Chart
        </button>
      </div>
      {view === "table" ? <AggregationResultTable result={result} /> : <BarChart data={data} valueFormatter={formatterFor(result, unit)} />}
    </div>
  );
}

/** Table/chart toggle for a trend (one AggregationResult per snapshot
 * date) -- a multi-series line chart of the same group x date grid the
 * pivoted table shows. */
export function TrendView({ trend, unit }: { trend: TrendPoint[]; unit?: string }) {
  const [view, setView] = useState<"table" | "chart">("table");
  if (trend.length === 0) return <p className="muted">No snapshots available.</p>;

  const dates = trend.map((t) => t.as_of);
  const weighted = trend[0].result.metric === "weighted_avg_datapoint";
  const groupValues = Array.from(new Set(trend.flatMap((t) => t.result.rows.map((r) => r.group_value)))).sort();
  const series: LineSeries[] = groupValues.map((gv) => ({
    label: gv,
    values: dates.map((d) => {
      const point = trend.find((t) => t.as_of === d);
      const row = point?.result.rows.find((r) => r.group_value === gv);
      if (!row) return null;
      return weighted ? row.weighted_avg_value ?? null : row.market_value_eur ?? null;
    }),
  }));
  const formatter = weighted
    ? (v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 2 }) + (unit ? ` ${unit}` : "")
    : (v: number) => `EUR ${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

  return (
    <div>
      <div className="view-toggle">
        <button className={view === "table" ? "active" : ""} onClick={() => setView("table")}>
          Table
        </button>
        <button className={view === "chart" ? "active" : ""} onClick={() => setView("chart")}>
          Chart
        </button>
      </div>
      {view === "table" ? <TrendTable trend={trend} /> : <LineChart dates={dates} series={series} valueFormatter={formatter} />}
    </div>
  );
}
