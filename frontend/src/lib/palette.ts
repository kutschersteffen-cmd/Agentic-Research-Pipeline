// Validated against this app's light chart surface (--panel: #fcfcfb) via
// the dataviz skill's validator (scripts/validate_palette.js): all four
// hard gates pass (lightness band, chroma floor, CVD adjacent-pair
// separation, normal-vision floor). Fixed order -- never cycle or re-sort
// per filter, so a series keeps its color as other series are added/
// removed ("color follows the entity, never its rank").
export const CATEGORICAL = [
  "#2a78d6", // slot 1: blue
  "#eb6834", // slot 2: orange
  "#1baf7a", // slot 3: aqua
  "#eda100", // slot 4: yellow
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
