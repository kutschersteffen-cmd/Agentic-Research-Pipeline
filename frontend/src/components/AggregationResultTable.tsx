import { dimensionLabel, eurText, formatEur, valueHeader } from "../lib/askPortfolio";
import type { AggregationResult } from "../types";

/** `scale` ("millions") and `unit` come with an Ask the Portfolio answer; without them figures are plain EUR. */
export function AggregationResultTable({ result, scale, unit }: { result: AggregationResult; scale?: string; unit?: string }) {
  const weighted = result.metric === "weighted_avg_datapoint";

  return (
    <div>
      <p className="muted">
        {result.spec_name} — grouped by {dimensionLabel(result.group_by)}, as of {result.as_of}
      </p>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>{dimensionLabel(result.group_by)}</th>
              <th>{valueHeader(result.metric, scale, unit)}</th>
              {weighted && <th>Coverage</th>}
              <th>Holdings</th>
            </tr>
          </thead>
          <tbody>
            {result.rows.map((row) => (
              <tr key={row.group_value}>
                <td>{row.group_value}</td>
                {weighted ? (
                  <td>{row.weighted_avg_value != null ? row.weighted_avg_value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : "no data"}</td>
                ) : (
                  <td>{row.market_value_eur != null ? formatEur(row.market_value_eur, scale) : "--"}</td>
                )}
                {weighted && <td>{row.coverage_pct != null ? `${(row.coverage_pct * 100).toFixed(1)}%` : "--"}</td>}
                <td>{row.holding_count}</td>
              </tr>
            ))}
            {result.rows.length === 0 && (
              <tr>
                <td colSpan={weighted ? 4 : 3} className="muted">
                  No matching holdings.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="muted">
        Total: {eurText(result.total_market_value_eur, scale)}
        {result.unresolved_market_value_eur > 0 && ` (${eurText(result.unresolved_market_value_eur, scale)} excluded for missing data)`}
      </p>
    </div>
  );
}
