import test from "node:test";
import assert from "node:assert/strict";
import { clearTurns, historyFor, loadTurns, saveTurns } from "../src/lib/askHistory.ts";
import type { AskTurn } from "../src/lib/askHistory.ts";
import type { AskResponse } from "../src/types.ts";

const answered = (n: number): AskTurn => ({
  id: `t${n}`, question: `q${n}`, status: "answered",
  response: { tool: "portfolio", question: `q${n}`, standalone_question: `full q${n}` } as AskResponse,
});
const failed: AskTurn = { id: "bad", question: "boom", status: "error", error: "Ask could not answer this question. Try again." };

function memory(): Storage {
  const data = new Map<string, string>();
  return {
    getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k), clear: () => data.clear(), key: () => null, get length() { return data.size; },
  };
}
const broken = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }, removeItem() { throw new Error("blocked"); } } as unknown as Storage;

test("history is the newest 5 answered turns, oldest first", () => {  // AC-48
  const turns = [1, 2, 3, 4, 5, 6, 7].map(answered);
  assert.deepEqual(historyFor(turns).map((t) => t.question), ["q3", "q4", "q5", "q6", "q7"]);
  assert.deepEqual(historyFor(turns)[0], { question: "q3", tool: "portfolio", standalone_question: "full q3" });
});

test("a turn that ended in an error is never sent", () => {  // AC-54
  assert.deepEqual(historyFor([answered(1), failed, answered(2)]).map((t) => t.question), ["q1", "q2"]);
});

test("turns survive a save and load", () => {
  const s = memory();
  saveTurns([answered(1), failed], s);
  assert.deepEqual(loadTurns(s), [answered(1), failed]);
});

test("a turn still working is saved as an error, so a reload never shows a stuck spinner", () => {
  const s = memory();
  saveTurns([{ id: "w", question: "q", status: "working" }], s);
  assert.deepEqual(loadTurns(s), [{ id: "w", question: "q", status: "error" }]);
});

test("clear empties storage", () => {
  const s = memory();
  saveTurns([answered(1)], s);
  clearTurns(s);
  assert.deepEqual(loadTurns(s), []);
});

test("blocked or missing storage never throws", () => {  // Review Focus 5
  assert.deepEqual(loadTurns(broken), []);
  assert.doesNotThrow(() => saveTurns([answered(1)], broken));
  assert.doesNotThrow(() => clearTurns(broken));
  assert.deepEqual(loadTurns(null), []);
});
