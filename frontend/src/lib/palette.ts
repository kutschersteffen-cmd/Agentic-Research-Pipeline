import { useThemeMode, type ThemeMode } from "../theme";

/* Chart colours, per mode. Dark is a *selected* set stepped for the dark
 * surface -- never the light set flipped, which fails outright: run 2 below.
 *
 * Every value here was checked with the dataviz skill's validator rather
 * than judged by eye, against this app's real surfaces (--panel, which is
 * what a chart actually sits on: #f3f5f8 light, #121417 dark -- an earlier
 * note in this file claimed #fcfcfb, a colour the app does not use):
 *
 *   node scripts/validate_palette.js "<slots>" --mode light  --surface "#f3f5f8"
 *   node scripts/validate_palette.js "<slots>" --mode dark   --surface "#121417"
 *   node scripts/validate_palette.js "<ramp>"  --ordinal --mode <mode> --surface <surface>
 *
 * Results:
 *   1. light categorical on #f3f5f8 -- PASS (contrast WARN on orange/aqua/
 *      yellow: the relief rule applies, so those charts carry value labels
 *      or a table view, which this app's charts do).
 *   2. light categorical on #121417 -- FAIL, lightness band (orange 0.671,
 *      yellow 0.764, outside the dark band 0.48-0.67). Hence a dark set.
 *   3. dark categorical on #121417 -- PASS on every gate.
 *   4. both sequential ramps -- the previous 7-step ramp FAILED the ordinal
 *      light-end gate on both surfaces (its end step sat at 1.21:1 light,
 *      1.54:1 dark, against a 2:1 floor -- a low value rendered as an
 *      almost invisible cell). Re-stepped to 6 steps per mode; both PASS.
 */

/** Fixed order -- never cycle or re-sort per filter, so a series keeps its
 *  colour as other series are added or removed ("colour follows the entity,
 *  never its rank"). */
const CATEGORICAL_LIGHT = [
  "#2a78d6", // slot 1: blue
  "#eb6834", // slot 2: orange
  "#1baf7a", // slot 3: aqua
  "#eda100", // slot 4: yellow
] as const;

/** The same four hues, stepped for the dark surface. */
const CATEGORICAL_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500"] as const;

/** Single-hue sequential ramps (magnitude: bar fills, pivot heat cells),
 *  ordered from the value floor upward. On light that runs light -> dark; on
 *  dark it runs dark -> light, because on either surface the step nearest
 *  the surface is the one that has to stay visible against it. */
const SEQUENTIAL_LIGHT = ["#79adf6", "#5394ee", "#307be0", "#1964c3", "#0e4fa0", "#083c7c"] as const;
const SEQUENTIAL_DARK = ["#145bb2", "#2470d4", "#3d88ed", "#5fa1fc", "#85baff", "#acd2ff"] as const;

export const CATEGORICAL: Record<ThemeMode, readonly string[]> = {
  light: CATEGORICAL_LIGHT,
  dark: CATEGORICAL_DARK,
};

export const SEQUENTIAL: Record<ThemeMode, readonly string[]> = {
  light: SEQUENTIAL_LIGHT,
  dark: SEQUENTIAL_DARK,
};

/** Fixed-order categorical colour for the nth series (0-indexed). Callers
 *  should cap the series count before reaching the wrap -- see the skill's
 *  series-count ladder. */
export function categoricalColor(index: number, mode: ThemeMode): string {
  const set = CATEGORICAL[mode];
  return set[index % set.length];
}

/** Maps a value into the mode's ramp given the range it sits in. */
export function sequentialFill(value: number, min: number, max: number, mode: ThemeMode): string {
  const ramp = SEQUENTIAL[mode];
  if (max <= min) return ramp[Math.floor(ramp.length / 2)];
  const t = Math.min(Math.max((value - min) / (max - min), 0), 1);
  return ramp[Math.round(t * (ramp.length - 1))];
}

/** Picks legible ink (white or near-black) for text placed inside a filled
 *  cell or segment -- the one case where a label may sit on a data colour,
 *  per the skill's inline-label exception. */
export function textColorForFill(hex: string): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.55 ? "#0b0b0b" : "#ffffff";
}

/** What a chart component uses: the palette already bound to the surface it
 *  is being drawn on, and re-rendered when the viewer switches theme. */
export function useChartPalette() {
  const mode = useThemeMode();
  return {
    mode,
    categorical: CATEGORICAL[mode],
    sequential: SEQUENTIAL[mode],
    categoricalColor: (index: number) => categoricalColor(index, mode),
    sequentialFill: (value: number, min: number, max: number) => sequentialFill(value, min, max, mode),
  };
}
