import type { StepSettings } from "../types";

type Settings = Record<string, unknown>;

/** The mode whose every setting the run currently has (an override, else the app default), or null. */
export function modeOf(modes: Record<string, StepSettings>, value: StepSettings, defaults: Settings): string | null {
  const effective = (k: string) => (value as Settings)[k] ?? defaults[k];
  return Object.keys(modes).find((m) => Object.entries(modes[m]).every(([k, v]) => effective(k) === v)) ?? null;
}

/** `value` with `mode`'s settings in place of its own for those keys; a setting equal to the default is left out. */
export function withMode(mode: StepSettings, value: StepSettings, defaults: Settings): StepSettings {
  const next: Settings = { ...value };
  for (const [k, v] of Object.entries(mode)) {
    if (v === defaults[k]) delete next[k];
    else next[k] = v;
  }
  return next as StepSettings;
}
