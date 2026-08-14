import type { TrendPoint } from "../types";

/** Pivots a list of point-in-time results (one per snapshot date) into a
 * group x date table -- the same shape WACI trend and any Explore trend
 * query reduce to. */
export function TrendTable({ trend }: { trend: TrendPoint[] }) {
  const dates = trend.map((t) => t.as_of);
  const groupValues = Array.from(new Set(trend.flatMap((t) => t.result.rows.map((r) => r.group_value)))).sort();
  const weighted = trend[0]?.result.metric === "weighted_avg_datapoint";

  const valueAt = (groupValue: string, date: string) => {
    const point = trend.find((t) => t.as_of === date);
    const row = point?.result.rows.find((r) => r.group_value === groupValue);
    if (!row) return null;
    return weighted ? row.weighted_avg_value ?? null : row.market_value_eur ?? null;
  };

  return (
    <div className="inline-block">
      <table className="data-table">
        <thead>
          <tr>
            <th>Group</th>
            {dates.map((d) => (
              <th key={d}>{d}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groupValues.map((gv) => (
            <tr key={gv}>
              <td>{gv}</td>
              {dates.map((d) => {
                const v = valueAt(gv, d);
                return <td key={d}>{v != null ? v.toLocaleString(undefined, { maximumFractionDigits: weighted ? 2 : 0 }) : "--"}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
