import { useChartPalette } from "../lib/palette";
import type { HistogramBin, TierDefinition } from "../types";

/** Tier bands are ordinal (Tier 1 is best), so they take one hue from the
 * app's validated sequential ramp -- never a categorical rainbow. Tier 1
 * gets the step furthest from the chart surface, which is the darkest step
 * on light and the lightest on dark; the ramps are ordered from the surface
 * upward in both modes, so the same indices do the right thing either way.
 * Identity is never carried by color alone: the cut-points are drawn and
 * labelled on the axis, a legend names every band, and the ranked table
 * below the chart is the table view. */
/** Highest-contrast band first (Tier 1 is best), stepped down the ramp. */
const bandFills = (ramp: readonly string[]) => [ramp[5], ramp[4], ramp[3], ramp[2]];

function bandFor(score: number, cuts: number[]): number {
  for (let i = 0; i < cuts.length; i += 1) {
    if (score >= cuts[i]) return i;
  }
  return cuts.length;
}

/** Where the scores fell, and where the tiers cut them. The distribution is
 * the one view that shows whether a cut-point lands in a gap or slices
 * through a cluster -- which is the difference between a defensible band
 * and an arbitrary one. */
export function ScoreDistribution({
  bins,
  cuts,
  tiers,
}: {
  bins: HistogramBin[];
  cuts: number[];
  tiers: TierDefinition[];
}) {
  const { sequential } = useChartPalette();
  const BAND_FILLS = bandFills(sequential);

  if (bins.length === 0) return <p className="muted">Nothing scored yet, so there is no distribution to show.</p>;

  const width = 760;
  const height = 210;
  const padLeft = 38;
  const padRight = 14;
  const padTop = 12;
  const padBottom = 42;
  const plotWidth = width - padLeft - padRight;
  const plotHeight = height - padTop - padBottom;

  const low = bins[0].lower;
  const high = bins[bins.length - 1].upper;
  const span = high - low || 1;
  const maxCount = Math.max(...bins.map((b) => b.count), 1);
  const x = (value: number) => padLeft + ((value - low) / span) * plotWidth;
  const barWidth = Math.max(2, plotWidth / bins.length - 2); // 2px surface gap between fills

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="chart-svg" role="img" aria-label="Score distribution with tier cut-points">
        <line x1={padLeft} y1={padTop + plotHeight} x2={width - padRight} y2={padTop + plotHeight} className="chart-axis-line" />
        {[0, maxCount].map((tick) => (
          <text
            key={tick}
            x={padLeft - 8}
            y={padTop + plotHeight - (tick / maxCount) * plotHeight}
            textAnchor="end"
            dominantBaseline="middle"
            className="chart-axis-label"
          >
            {tick}
          </text>
        ))}
        {bins.map((bin) => {
          const barHeight = (bin.count / maxCount) * plotHeight;
          const mid = (bin.lower + bin.upper) / 2;
          const band = bandFor(mid, cuts);
          const y = padTop + plotHeight - barHeight;
          const radius = Math.min(4, barWidth / 2, barHeight);
          const left = x(bin.lower) + 1;
          const path =
            barHeight <= radius
              ? `M ${left},${y} h ${barWidth} v ${barHeight} h ${-barWidth} Z`
              : `M ${left},${y + radius} q 0,${-radius} ${radius},${-radius} h ${barWidth - radius * 2} q ${radius},0 ${radius},${radius} v ${barHeight - radius} h ${-barWidth} Z`;
          return (
            <path key={bin.lower} d={barHeight > 0 ? path : ""} fill={BAND_FILLS[Math.min(band, BAND_FILLS.length - 1)]}>
              <title>{`${bin.lower.toFixed(1)}-${bin.upper.toFixed(1)}: ${bin.count} ${bin.count === 1 ? "entity" : "entities"} (${tiers[Math.min(band, tiers.length - 1)]?.name ?? ""})`}</title>
            </path>
          );
        })}
        {cuts.map((cut) => (
          <g key={cut}>
            {/* A surface-colored ring under the rule keeps it readable where
                it crosses a dark bar -- the cut-point is the point of this
                chart and must not disappear into the band it creates. */}
            <line x1={x(cut)} y1={padTop} x2={x(cut)} y2={padTop + plotHeight} className="chart-cut-halo" />
            <line x1={x(cut)} y1={padTop} x2={x(cut)} y2={padTop + plotHeight} className="chart-cut-line" />
            <text x={x(cut)} y={padTop + plotHeight + 14} textAnchor="middle" className="chart-axis-label">
              {cut.toFixed(1)}
            </text>
          </g>
        ))}
        <text x={padLeft} y={height - 6} className="chart-axis-label">
          {low.toFixed(0)}
        </text>
        <text x={width - padRight} y={height - 6} textAnchor="end" className="chart-axis-label">
          {high.toFixed(0)}
        </text>
      </svg>
      <div className="chart-legend">
        {tiers.map((tier, index) => (
          <span key={tier.rank} className="chart-legend-item">
            <span className="chart-legend-swatch" style={{ background: BAND_FILLS[Math.min(index, BAND_FILLS.length - 1)] }} />
            {tier.name}
          </span>
        ))}
      </div>
    </div>
  );
}
