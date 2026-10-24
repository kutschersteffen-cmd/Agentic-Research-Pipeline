import type { ReviewItem, RunManifest } from "../types";

// The Argus start page (#/argus), derived from /api/runs and /api/review/items.

export type ArgusStatus = "Draft" | "Running" | "Needs you" | "Stopped" | "Failed" | "Finished";
export type ArgusStep = 1 | 2 | 3 | 4 | 5;

export interface ArgusRow {
  runId: string;
  label: string;
  companies: number;
  step: ArgusStep;
  status: ArgusStatus;
  startedBy: string | null;
  starterName: string | null;
  createdAt: string;
  openHref: string;
}

export const ARGUS_RUN_TYPES = ["extraction", "financials", "tnfd", "transition_plan"];
export const STEPS = ["Companies", "Documents", "Schema", "Extract", "Results"];

const LABELS: Record<string, string> = { financials: "Financials", tnfd: "TNFD", transition_plan: "Transition Plan" };

function label(r: RunManifest): string {
  if (r.run_type !== "extraction") return LABELS[r.run_type];
  const name = typeof r.params?.schema_name === "string" ? r.params.schema_name : "Extraction";
  const version = /:v(\d+)$/.exec(String(r.params?.schema_version ?? ""))?.[1];
  return version ? `${name} v${version}` : name;
}

function stepAndStatus(r: RunManifest, open: Set<string>): [ArgusStep, ArgusStatus] {
  if (r.status === "completed" || r.status === "partially_completed") return [5, open.has(r.run_id) ? "Needs you" : "Finished"];
  if (r.status === "cancelled") return [4, "Stopped"];
  if (r.status === "failed") return [4, "Failed"];
  return [4, "Running"];
}

/** Argus runs only, newest first. A finished run needs you while any of its review items is still open. */
export function argusRows(runs: RunManifest[], items: ReviewItem[]): ArgusRow[] {
  const open = new Set(items.map((i) => i.run_id));
  return runs
    .filter((r) => ARGUS_RUN_TYPES.includes(r.run_type))
    .map((r) => {
      const [step, status] = stepAndStatus(r, open);
      const starter = typeof r.params?.started_by === "string" ? r.params.started_by : null;
      return {
        runId: r.run_id,
        label: label(r),
        companies: r.company_count,
        step,
        status,
        startedBy: starter,
        starterName: typeof r.params?.started_by_name === "string" ? r.params.started_by_name : starter,
        createdAt: r.created_at,
        // shortcut: the old screens until slice 5 builds steps 4 and 5
        openHref: step === 5 ? "#/review" : "#/extraction/extract",
      };
    })
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

/** `mineOf` is the signed-in user's id when Only mine is on; runs with no recorded starter are then hidden. */
export function filterRows(rows: ArgusRow[], f: { step: number | null; mineOf: string | null }): ArgusRow[] {
  return rows.filter((r) => (f.step === null || r.step === f.step) && (f.mineOf === null || r.startedBy === f.mineOf));
}

const ownItems = (rows: ArgusRow[], items: ReviewItem[]) => {
  const ids = new Set(rows.map((r) => r.runId));
  return items.filter((i) => ids.has(i.run_id));
};

/** Open items of these rows only (other workspaces' items are never counted); empty groups are left out. */
export function waiting(rows: ArgusRow[], items: ReviewItem[]): { total: number; groups: { label: string; count: number }[] } {
  const own = ownItems(rows, items);
  const docs = own.filter((i) => i.kind === "quarantined_document").length;
  const groups = [
    { label: "Conflicts", count: 0 }, // shortcut: conflicts arrive with the data rule in slice 7
    { label: "Values to review", count: own.length - docs },
    { label: "Documents to check", count: docs },
    { label: "Errors", count: rows.filter((r) => r.status === "Failed").length },
  ].filter((g) => g.count > 0);
  return { total: groups.reduce((n, g) => n + g.count, 0), groups };
}

/** The five Process tiles: runs per step, and what waits there. */
export function tiles(rows: ArgusRow[], items: ReviewItem[]): { step: number; label: string; count: number; needs: string | null }[] {
  return STEPS.map((name, i) => {
    const step = i + 1;
    const here = rows.filter((r) => r.step === step);
    const values = step === 5 ? ownItems(here, items).length : 0;
    const failed = step === 4 ? here.filter((r) => r.status === "Failed").length : 0;
    const needs = values ? `${values} values need you` : failed ? `${failed} failed` : null;
    return { step, label: name, count: here.length, needs };
  });
}
