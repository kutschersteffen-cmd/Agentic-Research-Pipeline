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

/** One row of the thread list: a plan or an ask thread. */
export type ThreadRow = { kind: "plan" | "ask"; id: string; title: string; status: string; created_at: string };

/** Plans and ask threads in one list, newest first by `created_at`. */
export function threadRows(plans: Plan[], asks: AskThread[]): ThreadRow[] {
  return [
    ...plans.map((p) => ({ kind: "plan" as const, id: p.id, title: threadTitle(p.brief), status: p.status, created_at: p.created_at })),
    ...asks.map((a) => ({ kind: "ask" as const, id: a.thread_id, title: a.title, status: a.status, created_at: a.created_at })),
  ].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
}
