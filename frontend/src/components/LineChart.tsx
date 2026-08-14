import { useState } from "react";
import { categoricalColor } from "../lib/palette";

export interface LineSeries {
  label: string;
  values: (number | null)[]; // aligned to the shared `dates` array; null = no data at that date
}

// Standard "nice number" axis rounding so ticks land on clean values
// (0 / 1,000 / 2,000) instead of raw fractions of the data's max.
function niceNumber(range: number, round: boolean): number {
  if (range <= 0) return 1;
  const exponent = Math.floor(Math.log10(range));
  const fraction = range / 10 ** exponent;
  let niceFraction: number;
  if (round) {
    if (fraction < 1.5) niceFraction = 1;
    else if (fraction < 3) niceFraction = 2;
    else if (fraction < 7) niceFraction = 5;
    else niceFraction = 10;
  } else {
    if (fraction <= 1) niceFraction = 1;
    else if (fraction <= 2) niceFraction = 2;
    else if (fraction <= 5) niceFraction = 5;
    else niceFraction = 10;
  }
  return niceFraction * 10 ** exponent;
}

function niceAxisTicks(maxValue: number, tickCount = 4): number[] {
  if (maxValue <= 0) return [0, 1];
  const step = niceNumber(niceNumber(maxValue, false) / (tickCount - 1), true);
  const niceMax = Math.ceil(maxValue / step) * step;
  const ticks: number[] = [];
  for (let v = 0; v <= niceMax + step / 2; v += step) ticks.push(Math.round(v * 100) / 100);
  return ticks;
}

/** Multi-series line chart -- distinct series is the job, so color is
 * categorical (fixed slot order, never re-sorted). Ships a crosshair +
 * one-tooltip-every-series on hover per the dataviz skill: every value a
 * tooltip shows is also reachable without it, via the axis, the legend,
 * and the table view.
 */
export function LineChart({
  dates,
  series,
  valueFormatter = (v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 2 }),
}: {
  dates: string[];
  series: LineSeries[];
  valueFormatter?: (v: number) => string;
}) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  if (dates.length === 0 || series.length === 0) {
    return <p className="muted">No data to chart.</p>;
  }

  const width = 760;
  const height = 300;
  const marginLeft = 64;
  const marginRight = 118; // room for the value-at-end-of-line direct labels -- never let them clip
  const marginTop = 16;
  const marginBottom = 32;
  const plotWidth = width - marginLeft - marginRight;
  const plotHeight = height - marginTop - marginBottom;

  const allValues = series.flatMap((s) => s.values.filter((v): v is number => v != null));
  const maxValue = allValues.length ? Math.max(...allValues) : 1;
  const yTicks = niceAxisTicks(maxValue);
  const yMax = yTicks[yTicks.length - 1];

  const xAt = (i: number) => marginLeft + (dates.length > 1 ? (i / (dates.length - 1)) * plotWidth : plotWidth / 2);
  const yAt = (v: number) => marginTop + plotHeight - (v / yMax) * plotHeight;

  // Direct end-labels: a short line-key (the identity channel) plus the
  // value in neutral ink -- text never wears the series color. Value only,
  // not the series name, so the label stays short enough to never clip
  // regardless of how long a group name is; the legend above carries the
  // name for 2+ series, and a single series needs no legend per the
  // dataviz skill (the section heading already says what's plotted).
  const endLabels = series
    .map((s, i) => {
      let lastIdx = -1;
      for (let idx = s.values.length - 1; idx >= 0; idx--) {
        if (s.values[idx] != null) {
          lastIdx = idx;
          break;
        }
      }
      if (lastIdx < 0) return null;
      const value = s.values[lastIdx] as number;
      return { label: s.label, color: categoricalColor(i), x: xAt(lastIdx), y: yAt(value), value };
    })
    .filter((d): d is NonNullable<typeof d> => d !== null)
    .sort((a, b) => a.y - b.y);
  const minGap = 14;
  for (let i = 1; i < endLabels.length; i++) {
    if (endLabels[i].y - endLabels[i - 1].y < minGap) endLabels[i].y = endLabels[i - 1].y + minGap;
  }

  function handleMove(e: React.MouseEvent<SVGRectElement>) {
    const svg = e.currentTarget.ownerSVGElement;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * width;
    const rel = (px - marginLeft) / plotWidth;
    const idx = Math.round(rel * (dates.length - 1));
    setHoverIdx(Math.min(Math.max(idx, 0), dates.length - 1));
  }

  const tooltipPct = hoverIdx != null ? Math.min(Math.max((xAt(hoverIdx) / width) * 100, 10), 85) : 0;

  return (
    <div>
      {series.length >= 2 && (
        <div className="chart-legend">
          {series.map((s, i) => (
            <span key={s.label} className="chart-legend-item">
              <span className="chart-legend-swatch" style={{ background: categoricalColor(i) }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
      <div className="chart-wrap">
      <svg viewBox={`0 0 ${width} ${height}`} className="chart-svg" role="img" aria-label="Line chart">
        {yTicks.map((t) => (
          <g key={t}>
            <line x1={marginLeft} y1={yAt(t)} x2={width - marginRight} y2={yAt(t)} className="chart-gridline" />
            <text x={marginLeft - 8} y={yAt(t)} textAnchor="end" dominantBaseline="middle" className="chart-axis-label">
              {t.toLocaleString(undefined, { maximumFractionDigits: 1 })}
            </text>
          </g>
        ))}
        {dates.map((d, i) => (
          <text key={d} x={xAt(i)} y={height - 10} textAnchor="middle" className="chart-axis-label">
            {d}
          </text>
        ))}
        {hoverIdx != null && (
          <line x1={xAt(hoverIdx)} y1={marginTop} x2={xAt(hoverIdx)} y2={marginTop + plotHeight} className="chart-crosshair" />
        )}
        {series.map((s, i) => {
          const color = categoricalColor(i);
          const points = s.values
            .map((v, idx) => (v != null ? `${xAt(idx)},${yAt(v)}` : null))
            .filter((p): p is string => p !== null)
            .join(" ");
          return (
            <g key={s.label}>
              <polyline points={points} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
              {s.values.map(
                (v, idx) =>
                  v != null && <circle key={idx} cx={xAt(idx)} cy={yAt(v)} r={4} fill={color} stroke="#171a21" strokeWidth={2} />
              )}
            </g>
          );
        })}
        {endLabels.map((e) => (
          <g key={e.label}>
            <line x1={e.x + 2} y1={e.y} x2={e.x + 10} y2={e.y} stroke={e.color} strokeWidth={2} strokeLinecap="round" />
            <text x={e.x + 14} y={e.y} dominantBaseline="middle" className="chart-end-label">
              {valueFormatter(e.value)}
            </text>
          </g>
        ))}
        <rect
          x={marginLeft}
          y={marginTop}
          width={plotWidth}
          height={plotHeight}
          fill="transparent"
          onMouseMove={handleMove}
          onMouseLeave={() => setHoverIdx(null)}
        />
      </svg>
      {hoverIdx != null && (
        <div className="chart-tooltip" style={{ left: `${tooltipPct}%` }}>
          <div className="chart-tooltip-date">{dates[hoverIdx]}</div>
          {series.map((s, i) => {
            const v = s.values[hoverIdx as number];
            return (
              <div key={s.label} className="chart-tooltip-row">
                <span className="chart-legend-swatch" style={{ background: categoricalColor(i) }} />
                <span className="chart-tooltip-value">{v != null ? valueFormatter(v) : "no data"}</span>
                <span className="muted">{s.label}</span>
              </div>
            );
          })}
        </div>
      )}
      </div>
    </div>
  );
}
