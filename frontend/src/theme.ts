import { useSyncExternalStore } from "react";

export type ThemeChoice = "system" | "light" | "dark";
export type ThemeMode = "light" | "dark";

const KEY = "arp:theme";
const listeners = new Set<() => void>();
const media = typeof window !== "undefined" ? window.matchMedia("(prefers-color-scheme: dark)") : null;

function readChoice(): ThemeChoice {
  try {
    const stored = localStorage.getItem(KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    // Blocked storage costs the preference, nothing else.
    return "system";
  }
}

let choice: ThemeChoice = readChoice();

function resolve(): ThemeMode {
  if (choice !== "system") return choice;
  return media?.matches ? "dark" : "light";
}

/** Only an explicit choice is stamped on the document: left alone, the OS
 *  setting drives the theme through the media query, so there is no flash of
 *  the wrong theme while JavaScript boots. */
function apply() {
  const el = document.documentElement;
  if (choice === "system") delete el.dataset.theme;
  else el.dataset.theme = choice;
}

function emit() {
  for (const listener of listeners) listener();
}

media?.addEventListener("change", emit);
apply();

export function setTheme(next: ThemeChoice) {
  choice = next;
  try {
    localStorage.setItem(KEY, next);
  } catch {
    // Same as above: the choice still applies to this session.
  }
  apply();
  emit();
}

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
}

const snapshot = () => `${choice}|${resolve()}`;

export function useTheme(): { choice: ThemeChoice; mode: ThemeMode; setTheme: (next: ThemeChoice) => void } {
  const snap = useSyncExternalStore(subscribe, snapshot, () => "system|light");
  const [storedChoice, mode] = snap.split("|") as [ThemeChoice, ThemeMode];
  return { choice: storedChoice, mode, setTheme };
}

/** The chart surface the marks will sit on, for code that has to pick a
 *  colour rather than name a token. */
export function useThemeMode(): ThemeMode {
  return useTheme().mode;
}

/* --- Table density -------------------------------------------------------
   One setting for all ~60 tables rather than a control on each. */

export type Density = "comfortable" | "compact";
const DENSITY_KEY = "arp:density";
const densityListeners = new Set<() => void>();

function readDensity(): Density {
  try {
    return localStorage.getItem(DENSITY_KEY) === "compact" ? "compact" : "comfortable";
  } catch {
    return "comfortable";
  }
}

let density: Density = readDensity();

function applyDensity() {
  document.documentElement.dataset.density = density;
}

applyDensity();

export function setDensity(next: Density) {
  density = next;
  try {
    localStorage.setItem(DENSITY_KEY, next);
  } catch {
    // Preference only.
  }
  applyDensity();
  for (const listener of densityListeners) listener();
}

export function useDensity(): { density: Density; setDensity: (next: Density) => void } {
  const value = useSyncExternalStore(
    (onChange) => {
      densityListeners.add(onChange);
      return () => densityListeners.delete(onChange);
    },
    () => density,
    () => "comfortable" as Density
  );
  return { density: value, setDensity };
}
