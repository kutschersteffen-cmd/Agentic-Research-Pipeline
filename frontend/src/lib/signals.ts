import type { Me } from "./reviewKeys";
import type { CutoffStatus, SignalComparison, SignalMethod, SignalWindow } from "../types";

const UNKNOWN = "cutoff unknown: not evidence";

export const windowLabel = (window: SignalWindow["window"], status: CutoffStatus): string | null =>
  window === "in_window" && status === "recorded" ? "contaminated (in the model's training window)" : null;

export const cutoffNotice = (status: CutoffStatus): string | null => (status === "unknown" ? UNKNOWN : null);

export function decisionBlocks(role: Me["role"] | null, status: CutoffStatus): { graduate: string | null; shelve: string | null } {
  if (role !== "approver") return { graduate: "Requires approver", shelve: "Requires approver" };
  return { graduate: cutoffNotice(status), shelve: null };
}

export const methodNote = (m: SignalMethod): string | null => (m.runnable_in_app ? null : "Run from the CLI or a notebook");

const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;

export function compareMessage(c: SignalComparison, methodOf: (id: string) => string): string {
  const counts = `(${count(c.months, "month")}, ${count(c.n_comparisons, "comparison")})`;
  const id = c.verdict === "b_higher" ? c.b : c.a;
  const head = c.verdict === "insufficient_data" ? `Insufficient data: these signals cannot be separated ${counts}` : `${methodOf(id)} ${id} is higher ${counts}`;
  return c.reason ? `${head} ${c.reason}` : head;
}

/** An IC figure with 3 decimals; a missing one as a dash. */
export const ic = (v: number | null | undefined): string => (v == null ? "—" : v.toFixed(3));

/** `YYYY-MM-DD HH:MM` in the browser's local time. */
export function createdLabel(iso: string): string {
  const t = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${t.getFullYear()}-${p(t.getMonth() + 1)}-${p(t.getDate())} ${p(t.getHours())}:${p(t.getMinutes())}`;
}

export const shortId = (id: string): string => id.slice(0, 8);

/** Shown when a run answers an experiment the list already has (same recipe, same data). */
export const alreadyRunLine = (id: string): string =>
  `This recipe was already run on this data. Showing the existing result (${id}).`;

/** Relative, so they resolve under a proxy prefix (JupyterLab) as well as at the root. */
export const SAMPLE_RECIPE = "samples/signals-recipe.json";
export const SAMPLE_PRICES = "samples/signals-prices.csv";
