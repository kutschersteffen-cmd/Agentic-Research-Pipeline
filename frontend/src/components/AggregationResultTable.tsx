import type { AggregationResult } from "../types";

function formatEur(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

export function AggregationResultTable({ result }: { result: AggregationResult }) {
  const weighted = result.metric === "weighted_avg_datapoint";

  return (
    <div>
      <p className="muted">
        {result.spec_name} -- grouped by {result.group_by}, as of {result.as_of}
      </p>
      <table className="data-table">
        <thead>
          <tr>
            <th>{result.group_by}</th>
            {weighted ? <th>Weighted avg</th> : <th>Market value (EUR)</th>}
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
                <td>{row.market_value_eur != null ? formatEur(row.market_value_eur) : "--"}</td>
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
      <p className="muted">
        Total: EUR {formatEur(result.total_market_value_eur)}
        {result.unresolved_market_value_eur > 0 && ` (EUR ${formatEur(result.unresolved_market_value_eur)} excluded for missing data)`}
      </p>
    </div>
  );
}
