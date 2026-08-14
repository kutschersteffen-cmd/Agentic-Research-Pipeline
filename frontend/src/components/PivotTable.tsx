import type { PivotResult } from "../types";
import { sequentialFill, textColorForFill } from "../lib/palette";

function cellValue(result: PivotResult, rowValue: string, colValue: string) {
  return result.cells.find((c) => c.row_value === rowValue && c.col_value === colValue) ?? null;
}

function metricValue(result: PivotResult, cell: ReturnType<typeof cellValue>): number | null {
  if (!cell) return null;
  if (result.metric === "weighted_avg_datapoint") return cell.weighted_avg_value ?? null;
  if (result.metric === "count") return cell.holding_count;
  return cell.market_value_eur ?? null;
}

/** A two-dimension cross-tab rendered as a heatmap table: magnitude is the
 * job here (a value per row x col combination), so cell shading is the
 * single sequential hue, never categorical -- per dataviz skill's
 * "compare magnitude -> heatmap, sequential color" rule. Every value is
 * also printed as text (the table view itself), so the color is a
 * secondary read, not the only one. */
export function PivotTable({ result }: { result: PivotResult }) {
  const values = result.cells.map((c) => metricValue(result, c)).filter((v): v is number => v != null);
  const min = values.length ? Math.min(...values, 0) : 0;
  const max = values.length ? Math.max(...values) : 1;

  return (
    <div className="pivot-table-wrap">
      <p className="muted">
        {result.spec_name} -- {result.row_dim} x {result.col_dim}, as of {result.as_of}
      </p>
      <table className="pivot-table">
        <thead>
          <tr>
            <th>{result.row_dim}</th>
            {result.col_values.map((cv) => (
              <th key={cv}>{cv}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.row_values.map((rv) => (
            <tr key={rv}>
              <td>{rv}</td>
              {result.col_values.map((cv) => {
                const cell = cellValue(result, rv, cv);
                const value = metricValue(result, cell);
                if (cell === null || value === null) {
                  return (
                    <td key={cv} className="pivot-cell-empty">
                      --
                    </td>
                  );
                }
                const fill = sequentialFill(value, min, max);
                const ink = textColorForFill(fill);
                const label = result.metric === "weighted_avg_datapoint" ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : value.toLocaleString(undefined, { maximumFractionDigits: 0 });
                return (
                  <td key={cv} style={{ background: fill, color: ink }} title={`${rv} / ${cv}: ${label}${cell.coverage_pct != null ? ` (coverage ${(cell.coverage_pct * 100).toFixed(1)}%)` : ""}`}>
                    {label}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">
        Total: EUR {result.total_market_value_eur.toLocaleString(undefined, { maximumFractionDigits: 0 })}
        {result.unresolved_market_value_eur > 0 &&
          ` (EUR ${result.unresolved_market_value_eur.toLocaleString(undefined, { maximumFractionDigits: 0 })} excluded for missing data)`}
      </p>
    </div>
  );
}
