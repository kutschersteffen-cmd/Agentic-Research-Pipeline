import type { RunManifest } from "../types.ts";
import { REVIEWABLE_RUN_TYPES, runTypeLabel } from "./runs.ts";

export type PaletteItem = { label: string; hint?: string; href: string };

/** A run in the palette opens where its decisions are made, else on its own row in Run History. */
export const runItem = (r: RunManifest): PaletteItem => ({
  label: `${runTypeLabel(r.run_type)} ${r.run_id}`,
  hint: "Run",
  href:
    r.run_type === "proxy_voting"
      ? `#/voting/${r.run_id}`
      : REVIEWABLE_RUN_TYPES.has(r.run_type)
        ? `#/review/${r.run_type}/${r.run_id}`
        : `#/history/${encodeURIComponent(r.run_id)}`,
});
