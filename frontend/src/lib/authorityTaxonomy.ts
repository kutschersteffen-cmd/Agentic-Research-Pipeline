import type { AuthorityRunRequest, AuthorityRunState } from "../types";

export const THEME_KEYS: readonly { key: string; label: string }[] = [
  { key: "hydrogen", label: "Hydrogen" },
  { key: "renewable_power", label: "Renewable power" },
  { key: "energy_storage", label: "Energy storage" },
  { key: "electric_vehicles", label: "Electric vehicles" },
  { key: "grid_electrification", label: "Grid electrification" },
  { key: "ai_datacentres", label: "AI data centres" },
  { key: "water", label: "Water" },
  { key: "ccus", label: "Carbon capture, utilisation and storage" },
  { key: "critical_minerals_circular", label: "Critical minerals and circularity" },
  { key: "building_efficiency", label: "Building efficiency" },
];

export const CHECKLIST_KEYS = [
  "theme_description", "activities", "boundaries", "technologies", "definitions", "sector_codes", "value_chain", "thresholds",
] as const;

export const POLL_MS = 3000;

export type StartForm = { theme_name: string; theme_key: string | null; scope: string; guidance: string; value_chain: boolean };

export function startBody(f: StartForm): { body: AuthorityRunRequest } | { error: "Theme name is required" } {
  const theme_name = f.theme_name.trim();
  if (!theme_name) return { error: "Theme name is required" };
  return { body: { theme_name, theme_key: f.theme_key, scope: f.scope, guidance: f.guidance, value_chain: f.value_chain } };
}

export const prefill = (run: AuthorityRunState): StartForm => ({
  theme_name: run.theme_name, theme_key: run.theme_key ?? null, scope: run.scope, guidance: run.guidance, value_chain: run.value_chain,
});

export type Selection = { ticked: string[]; urls: string[]; files: { name: string; path: string }[]; uploading: number };

export function initialSelection(run: AuthorityRunState): Selection {
  if (!run.selection) {
    const ticked = run.candidates.filter((c) => c.from_library && c.fetchable).map((c) => c.url);
    return { ticked, urls: [], files: [], uploading: 0 };
  }
  const known = new Set(run.candidates.map((c) => c.url));
  const { urls, files } = run.selection;
  return {
    ticked: urls.filter((u) => known.has(u)),
    urls: urls.filter((u) => !known.has(u)),
    files: files.map((path) => ({ name: path.split(/[\\/]/).pop() ?? path, path })),
    uploading: 0,
  };
}

export const sourcesBody = (s: Selection): { urls: string[]; files: string[] } => ({
  urls: [...s.ticked, ...s.urls],
  files: s.files.map((f) => f.path),
});

export const canBuild = (s: Selection): boolean => s.uploading === 0 && s.ticked.length + s.urls.length + s.files.length > 0;

export const isWorking = (stage: string): boolean => stage === "discovering" || stage === "extracting";

export type View = "not_found" | "working" | "sources" | "review" | "accepted" | "ended";

export function viewFor(run: AuthorityRunState | null): View {
  if (!run) return "not_found";
  if (isWorking(run.stage)) return "working";
  if (run.stage === "awaiting_sources") return "sources";
  if (run.stage === "awaiting_review") return "review";
  return run.stage === "accepted" ? "accepted" : "ended";
}

type Doc = Pick<Document, "visibilityState" | "addEventListener" | "removeEventListener">;

/** Loads at once, then again 3 s after each answer while the run is working and the tab is visible;
 * becoming visible again polls once at once. Returns a stop function; its `resume()` polls again after
 * the user moves the run back to a working stage (Build draft). */
export function startPolling(
  get: () => Promise<AuthorityRunState>, onState: (r: AuthorityRunState) => void, doc: Doc, onError: (e: unknown) => void = () => {},
): (() => void) & { resume: () => void } {
  let stopped = false;
  let working = true;
  let busy = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const poll = async () => {
    if (stopped || busy) return;
    clearTimeout(timer);
    busy = true;
    try {
      const run = await get();
      if (stopped) return;
      working = isWorking(run.stage);
      onState(run);
    } catch (e) {
      working = false;
      if (!stopped) onError(e);
    } finally {
      busy = false;
    }
    if (working && !stopped) {
      timer = setTimeout(() => {
        if (doc.visibilityState === "visible") void poll(); // hidden: the visibility handler restarts the chain
      }, POLL_MS);
    }
  };
  const onVisible = () => {
    if (doc.visibilityState === "visible" && working) void poll();
  };
  doc.addEventListener("visibilitychange", onVisible);
  void poll();
  const stop = () => {
    stopped = true;
    clearTimeout(timer);
    doc.removeEventListener("visibilitychange", onVisible);
  };
  return Object.assign(stop, { resume: () => { working = true; void poll(); } });
}

export async function saveThenAccept(
  dirty: boolean, save: () => Promise<unknown>, accept: () => Promise<{ taxonomy_id: string }>,
): Promise<{ taxonomy_id: string }> {
  if (dirty) await save();
  return accept();
}

/** Edits an item's own fields; its citations are never part of the patch. */
export function editText<T extends { citations: unknown[] }>(item: T, patch: Partial<Omit<T, "citations">>): T {
  return { ...item, ...patch, citations: item.citations };
}
