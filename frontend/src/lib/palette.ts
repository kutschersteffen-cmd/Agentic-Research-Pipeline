// Categorical slots are CSS custom properties (--cat-1..4 in index.css) so
// they follow the Graphite/Night theme; use them in style props, not SVG
// presentation attributes (those don't resolve var()).
//   Graphite on --panel #ffffff:  #2a78d6 4.4:1, #c2407f 4.9:1, #a87400 4.1:1, #6250d6 5.8:1
//   Night    on --panel #131417:  #3987e5 5.1:1, #d55181 4.7:1, #c98500 6.0:1, #9085e9 5.9:1
// Checked with the dataviz skill's validator (scripts/validate_palette.js,
// --surface set to each panel): lightness band, chroma floor, contrast >=3:1,
// and adjacent-pair CVD / normal-vision separation pass in both modes; the
// first three slots also pass all-pairs. Slot 1 vs slot 4 (blue/violet) fails
// all-pairs, so a 4-series chart leans on the legend + direct end labels.
// Slot 2 was orange (#eb6834), too close to the Graphite signal #ea4c14 --
// it read as "needs you"; magenta replaces it. No slot is green or red, so
// series don't impersonate --high/--low status either.
// Fixed order -- never cycle or re-sort per filter, so a series keeps its
// color as other series are added/removed ("color follows the entity,
// never its rank").
export const CATEGORICAL = [
  "var(--cat-1)", // blue
  "var(--cat-2)", // magenta
  "var(--cat-3)", // gold
  "var(--cat-4)", // violet
] as const;

// Single-hue sequential ramp (blue, light -> dark) for magnitude encodings
// (bar charts, score bands) -- one hue only, never a rainbow.
// This ramp is mode-invariant (same steps validated for both chart
// surfaces), so it's unchanged from the app's previous dark theme.
export const SEQUENTIAL_BLUE = [
  "#cde2fb", // 100
  "#9ec5f4", // 200
  "#6da7ec", // 300
  "#3987e5", // 400
  "#256abf", // 500
  "#184f95", // 600
  "#0d366b", // 700
] as const;

/** Fixed-order categorical color for the nth series (0-indexed), wrapping
 * with a visible warning only past the validated set's size -- callers
 * should cap series count before reaching here (see marks-and-anatomy.md's
 * series-count ladder). */
export function categoricalColor(index: number): string {
  return CATEGORICAL[index % CATEGORICAL.length];
}
