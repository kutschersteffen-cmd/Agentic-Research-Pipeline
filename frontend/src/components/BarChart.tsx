export interface BarDatum {
  label: string;
  value: number;
}

// Rounded only at the data end (away from the baseline), square at the
// baseline -- SVG <rect> can't do per-corner radius, so this builds the
// path by hand. Falls back to a plain rect when the bar is too short for
// the radius to read as anything but a smear.
function roundedEndBarPath(x: number, y: number, w: number, h: number, r: number): string {
  if (w <= 0) return "";
  const rad = Math.min(r, w, h / 2);
  if (w <= rad * 1.5) {
    return `M ${x},${y} H ${x + w} V ${y + h} H ${x} Z`;
  }
  return `M ${x},${y} H ${x + w - rad} Q ${x + w},${y} ${x + w},${y + rad} V ${y + h - rad} Q ${x + w},${y + h} ${x + w - rad},${y + h} H ${x} Z`;
}

/** Horizontal bar chart: one metric across categories -- magnitude is the
 * job, so every bar is one ink (--text), never a categorical rainbow.
 * Drawn at its own size rather than stretched, so labels stay body-sized. */
export function BarChart({
  data,
  valueFormatter = (v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 1 }),
}: {
  data: BarDatum[];
  valueFormatter?: (v: number) => string;
}) {
  if (data.length === 0) {
    return <p className="muted">No data to chart.</p>;
  }

  const width = 760;
  const labelWidth = 170;
  const rightPad = 100;
  const barAreaWidth = width - labelWidth - rightPad;
  const rowHeight = 30;
  const barHeight = 18;
  const height = data.length * rowHeight + 8;
  const maxValue = Math.max(...data.map((d) => Math.abs(d.value)), 1);
  // Screen readers get the numbers, not just "a chart".
  const summary = `Bar chart, ${data.length} ${data.length === 1 ? "bar" : "bars"}: ${data.map((d) => `${d.label} ${valueFormatter(d.value)}`).join("; ")}`;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="chart-svg bar-chart" role="img" aria-label={summary}>
      <line x1={labelWidth} y1={0} x2={labelWidth} y2={height} className="chart-axis-line" />
      {data.map((d, i) => {
        const y = i * rowHeight + 4;
        const barWidth = maxValue > 0 ? (Math.abs(d.value) / maxValue) * barAreaWidth : 0;
        return (
          <g key={d.label} className="chart-bar-row">
            <text x={labelWidth - 8} y={y + barHeight / 2} textAnchor="end" dominantBaseline="middle" className="chart-axis-label">
              {d.label}
            </text>
            <path d={roundedEndBarPath(labelWidth, y, barWidth, barHeight, 4)} className="chart-bar">
              <title>{`${d.label}: ${valueFormatter(d.value)}`}</title>
            </path>
            <text x={labelWidth + barWidth + 8} y={y + barHeight / 2} dominantBaseline="middle" className="chart-value-label">
              {valueFormatter(d.value)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
