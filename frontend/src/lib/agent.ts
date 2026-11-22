// The Agent screen's rules, kept out of the page so they are testable without rendering it
// (spec 2026-11-21-agent-panel-code-mode, Phase 3).
import type { AgentAsk, AskThread, InboxRow } from "../types";
import { askErrorText } from "./askError.ts";
import type { Plan } from "./plans";

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
export const needsYouLine = (n: number): string => `${n} more in Needs you`;

// Phase 7: ask threads (spec agent-panel-code-mode, D10 to D13).

export type Mode = "Ask" | "Plan";

/** The selected thread: a plan or an ask thread. */
export type Selection = { kind: "plan" | "ask"; id: string } | null;

/** The composer's mode buttons, and the one pressed when it opens: a viewer cannot ask. */
export const composerModes = (canAsk: boolean): { modes: Mode[]; initial: Mode } =>
  canAsk ? { modes: ["Ask", "Plan"], initial: "Ask" } : { modes: ["Plan"], initial: "Plan" };

/** The composer's label, submit button (and its text while sending) and help line per mode. */
export const COMPOSER_COPY: Record<Mode, { label: string; submit: string; sending: string; help: string; placeholder: string }> = {
  Ask: { label: "Question", submit: "Ask", sending: "Asking…", help: "Enter asks ARP; Shift+Enter adds a line.",
    placeholder: "What are the sector weights of MSCI World?" },
  Plan: { label: "Research brief", submit: "Draft plan", sending: "Drafting…",
    help: "Enter drafts a plan; Shift+Enter adds a line. Name a saved universe in the brief.",
    placeholder: 'Grid-storage companies in the saved universe "eu listed": extract green capex, score, report' },
};

/** What the composer sends on Enter: an ask (a follow-up when an ask thread is selected) or a plan brief.
 * `Plan` never sends `source_ask_id`. */
export function composerRequest(mode: Mode, text: string, selected: Selection): { path: string; body: Record<string, string> } {
  if (mode === "Plan") return { path: "/api/plans", body: { brief: text } };
  return { path: "/api/agent/asks", body: selected?.kind === "ask" ? { question: text, thread_id: selected.id } : { question: text } };
}

/** Where Ctrl/⌘J goes: the Agent screen with no thread selected, or nowhere for a viewer. */
export const ctrlJTarget = (canAsk: boolean): string | null => (canAsk ? "#/agent" : null);

/** The buttons under an answered ask. */
export const answerActions = (canAsk: boolean): string[] => (canAsk ? ["Draft a plan"] : []);

/** `Draft a plan`: a plan from the ask's standalone question, linked to the ask. Any failure resolves to its detail. */
export async function draftPlanFromAsk(
  ask: Pick<AgentAsk, "id" | "standalone_question">, request: (path: string, body: unknown) => Promise<Plan>,
): Promise<{ ok: true; plan: Plan } | { ok: false; error: string }> {
  try {
    return { ok: true, plan: await request("/api/plans", { brief: ask.standalone_question, source_ask_id: ask.id }) };
  } catch (e) {
    return { ok: false, error: askErrorText(e) };
  }
}

/** The ask in flight: its question and the thread it was sent in (`null` starts a new thread). */
export type Asking = { question: string; threadId: string | null } | null;

/** The in-flight question to show in the ask thread on screen (`askId`, `null` for none): only the thread it was sent from. */
export const askingIn = (asking: Asking, askId: string | null): string | null =>
  asking !== null && asking.threadId === askId ? asking.question : null;

/** Hands `load`'s result to `onValue` (or its error to `onError`) unless the returned cancel ran first,
 * so a response for a thread no longer on screen is dropped. */
export function untilCancelled<T>(load: Promise<T>, onValue: (v: T) => void, onError: (e: Error) => void): () => void {
  let live = true;
  load.then((v) => { if (live) onValue(v); }, (e: Error) => { if (live) onError(e); });
  return () => { live = false; };
}

/** One row of the thread list: a plan or an ask thread. */
export type ThreadRow = { kind: "plan" | "ask"; id: string; title: string; status: string; created_at: string };

/** Plans and ask threads in one list, newest first by `created_at`. */
export function threadRows(plans: Plan[], asks: AskThread[]): ThreadRow[] {
  return [
    ...plans.map((p) => ({ kind: "plan" as const, id: p.id, title: threadTitle(p.brief), status: p.status, created_at: p.created_at })),
    ...asks.map((a) => ({ kind: "ask" as const, id: a.thread_id, title: a.title, status: a.status, created_at: a.created_at })),
  ].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
}
