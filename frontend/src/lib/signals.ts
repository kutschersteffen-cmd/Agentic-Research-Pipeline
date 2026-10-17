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
