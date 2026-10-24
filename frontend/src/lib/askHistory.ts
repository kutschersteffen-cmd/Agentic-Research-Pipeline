import type { AskHistoryTurn, AskResponse } from "../types";

/** One question in the Ask ARP panel and what came back. */
export type AskTurn = { id: string; question: string; status: "working" | "answered" | "error"; response?: AskResponse; error?: string };

const KEY = "arp.ask.turns";
const MAX_HISTORY = 5; // POST /api/ask refuses more

const session = (): Storage | null => {
  try {
    return globalThis.sessionStorage ?? null;
  } catch {
    return null;
  }
};

/** The newest answered turns, oldest first, as the API's history. Failed turns have no tool, so they are never sent. */
export function historyFor(turns: AskTurn[]): AskHistoryTurn[] {
  return turns
    .filter((t) => t.status === "answered" && t.response)
    .slice(-MAX_HISTORY)
    .map((t) => ({ question: t.question, tool: t.response!.tool, standalone_question: t.response!.standalone_question }));
}

export function loadTurns(storage: Storage | null = session()): AskTurn[] {
  try {
    return JSON.parse(storage?.getItem(KEY) ?? "[]") as AskTurn[];
  } catch {
    return [];
  }
}

export function saveTurns(turns: AskTurn[], storage: Storage | null = session()): void {
  // A reload ends the request, so a turn still working is stored as failed.
  const stored = turns.map((t) => (t.status === "working" ? { id: t.id, question: t.question, status: "error" as const } : t));
  try {
    storage?.setItem(KEY, JSON.stringify(stored));
  } catch {
    // blocked storage: the conversation still lives in memory for this page
  }
}

export function clearTurns(storage: Storage | null = session()): void {
  try {
    storage?.removeItem(KEY);
  } catch {
    // nothing stored to clear
  }
}
