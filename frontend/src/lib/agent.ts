// The Agent screen's rules, kept out of the page so they are testable without rendering it
// (spec 2026-11-21-agent-panel-code-mode, Phase 3).
import type { InboxRow } from "../types";

/** A chip: a plan or step status as a person reads it (`awaiting_review` reads `awaiting review`). */
export const chipLabel = (status: string): string => status.replace(/_/g, " ");

/** A thread's title: the brief's first 60 characters. */
export const threadTitle = (brief: string): string => brief.slice(0, 60);

/** The script's lines for the Script tab, numbered from 1; a final newline adds no empty line. */
export function scriptLines(script: string): { n: number; text: string }[] {
  const lines = script.split("\n");
  if (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
  return lines.map((text, i) => ({ n: i + 1, text }));
}

/** Enter sends the composer; Shift+Enter, or Enter while an input method is composing, types a newline. */
export const sendsComposer = (e: { key: string; shiftKey: boolean; isComposing?: boolean }): boolean =>
  e.key === "Enter" && !e.shiftKey && !e.isComposing;

export type DiffOp = " " | "-" | "+";

/** The body of `diff -u` for two scripts, every line marked " " (both), "-" (only in `a`) or "+" (only in `b`), from
 * a longest common subsequence, with each change's removals before its additions. As in `diff`, a last line without
 * a newline differs from the same text with one. `removed` and `added` count the "-" and "+" lines. */
export function lineDiff(a: string, b: string): { removed: number; added: number; lines: { op: DiffOp; text: string }[] } {
  const split = (s: string) => {
    const parts = s.split("\n");
    const last = parts.pop()!; // "" when the script ends with a newline
    const lines = parts.map((text) => ({ text, key: `${text}\n` }));
    if (last !== "") lines.push({ text: last, key: last });
    return lines;
  };
  const x = split(a);
  const y = split(b);
  // lcs[i][j]: the longest common subsequence of x[i..] and y[j..].
  const lcs = Array.from({ length: x.length + 1 }, () => new Array<number>(y.length + 1).fill(0));
  for (let i = x.length - 1; i >= 0; i--) {
    for (let j = y.length - 1; j >= 0; j--) {
      lcs[i][j] = x[i].key === y[j].key ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const lines: { op: DiffOp; text: string }[] = [];
  let i = 0;
  let j = 0;
  while (i < x.length || j < y.length) {
    if (i < x.length && j < y.length && x[i].key === y[j].key) {
      lines.push({ op: " ", text: x[i++].text });
      j++;
    } else if (j >= y.length || (i < x.length && lcs[i + 1][j] >= lcs[i][j + 1])) {
      lines.push({ op: "-", text: x[i++].text });
    } else {
      lines.push({ op: "+", text: y[j++].text });
    }
  }
  return { removed: x.length - lcs[0][0], added: y.length - lcs[0][0], lines };
}

/** A step on the Diff tab: `started` once a call is stored for it, `skipped` when the plan ended (done or cancelled)
 * without reaching it, else `planned`. */
export type StepState = "planned" | "started" | "skipped";
export const stepState = (planStatus: string, hasCall: boolean): StepState =>
  hasCall ? "started" : planStatus === "done" || planStatus === "cancelled" ? "skipped" : "planned";

/** A cost as the Audit tab shows it: the API's number unrounded, padded to 2 decimals (1.2 reads $1.20). */
export function usd(n: number | null | undefined): string {
  if (n == null) return "–";
  const s = String(n); // the shortest decimal that is exactly this number
  if (/e/i.test(s)) return `$${n.toFixed(20).replace(/0+$/, "")}`; // 1e-7: plain digits, no exponent
  return `$${(s.split(".")[1] ?? "").length <= 2 ? n.toFixed(2) : s}`;
}

/** The Audit tab's budget line: `spent $x of $y`, or `spent $x, no budget set`. */
export const budgetLine = (spent: number, budget: number | null | undefined): string =>
  budget == null ? `spent ${usd(spent)}, no budget set` : `spent ${usd(spent)} of ${usd(budget)}`;

/** What an inbox row asks of the person. */
export const INBOX_KIND: Record<InboxRow["kind"], string> = { plan_approval: "Approve plan", step_review: "Review step", exploration: "Exploration" };

/** The inbox footer: what else waits outside the agent lanes (`total` of `GET /api/waiting`). */
export const reviewQueueLine = (n: number): string => `${n} more waiting in the Review Queue`;
