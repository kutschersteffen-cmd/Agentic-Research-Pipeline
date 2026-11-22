// The Agent screen's rules, kept out of the page so they are testable without rendering it
// (spec 2026-11-21-agent-panel-code-mode, Phase 3).
import type { Plan } from "./plans";
import type { Exploration, InboxRow } from "../types";

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

/** A row of the thread list: a plan or an exploration, with its chip. */
export interface ThreadRow { kind: "plan" | "exploration"; id: string; title: string; chip: string; href: string }

/** Plans and explorations in one list, newest first by `created_at` (Phase 3, Threads). */
export function threadRows(plans: Plan[], explorations: Exploration[]): ThreadRow[] {
  const rows = [
    ...plans.map((p) => ({ at: p.created_at ?? "", row: { kind: "plan" as const, id: p.id, title: threadTitle(p.brief), chip: p.status as string, href: `#/agent/${p.id}` } })),
    ...explorations.map((e) => ({ at: e.created_at, row: { kind: "exploration" as const, id: e.id, title: threadTitle(e.question), chip: e.label as string, href: `#/agent/exploration/${e.id}` } })),
  ];
  return rows.sort((a, b) => Date.parse(b.at || "0") - Date.parse(a.at || "0")).map((r) => r.row);
}

/** The badge an exploration's card shows until a person accepts it (AC-49); none once accepted. */
export const explorationBadge = (e: Pick<Exploration, "label">): string | null => (e.label === "accepted" ? null : "Exploratory: not reviewed");

type Cell = string | number | boolean | null;

/** An exploration's result as a table when it is a non-empty list of flat objects (every value a string, number,
 * boolean or null); columns in first-seen order. Anything else is shown as JSON, so this answers null. */
export function resultTable(result: unknown): { columns: string[]; rows: Cell[][] } | null {
  if (!Array.isArray(result) || result.length === 0) return null;
  const flat = (v: unknown) => v === null || ["string", "number", "boolean"].includes(typeof v);
  const plain = (r: unknown): r is Record<string, unknown> => typeof r === "object" && r !== null && !Array.isArray(r) && Object.values(r).every(flat);
  if (!result.every(plain)) return null;
  const columns = [...new Set(result.flatMap((r) => Object.keys(r)))];
  return { columns, rows: result.map((r) => columns.map((c) => (c in r ? (r[c] as Cell) : null))) };
}

/** The composer's label, submit button (idle, sending) and help line, with Explore toggled off or on. */
export const composerText = (explore: boolean) =>
  explore
    ? { label: "Question", submit: "Explore", sending: "Exploring…", help: "Enter runs an exploration; Shift+Enter adds a line." }
    : { label: "Research brief", submit: "Draft plan", sending: "Drafting…", help: "Enter drafts a plan; Shift+Enter adds a line. Name a saved universe in the brief." };
