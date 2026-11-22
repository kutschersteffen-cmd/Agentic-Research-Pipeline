import test from "node:test";
import assert from "node:assert/strict";
import {
  overflowing, REFINE_COPY, refineChanged, refineControls, refineDoc, refineErrorText, refineHistory, refineProgress, refineResultLines,
  refineRunning, refineTitle, threadRows,
} from "../src/lib/agent.ts";
import type { RefineThread, RefineTurn } from "../src/types.ts";

// Refine threads on the Agent screen (docs/superpowers/specs/2026-11-14-refine-chat-design.md, amendment 2026-11-22).

const turn = (over: Partial<RefineTurn>): RefineTurn => ({
  turn_id: 1, user_id: "dev", message: "m", reply: "r", status: "done", done: 0, total: 0, changed: [], not_changed: [],
  check_figures: [], error: null, created_at: "2026-11-22T10:00:00Z", ...over,
});

test("a viewer reads a Refine thread with no composer and no Undo (AC-71)", () => {
  assert.deepEqual(refineControls(false), { composer: false, undo: false, picker: true, emptyLine: "No changes yet." });
  assert.deepEqual(refineControls(true), { composer: true, undo: true, picker: true, emptyLine: "No changes yet. Type an instruction below." });
});

test("history is the newest 5 done turns, oldest first (AC-72)", () => {
  const turns = [1, 2, 3, 4, 5, 6].map((i) => turn({ turn_id: i, message: `m${i}`, reply: `r${i}` }));
  turns.push(turn({ turn_id: 7, message: "m7", reply: null, status: "failed" }));
  assert.deepEqual(refineHistory(turns), [2, 3, 4, 5, 6].map((i) => ({ message: `m${i}`, reply: `r${i}` })));
});

test("undone and running turns are not sent as history", () => {
  const turns = [turn({ message: "a", status: "undone" }), turn({ message: "b" }), turn({ message: "c", status: "running", reply: null })];
  assert.deepEqual(refineHistory(turns), [{ message: "b", reply: "r" }]);
});

test("an RFP turn's lines name questions as Q<id> (AC-72b)", () => {
  const t = turn({ changed: [1, 2], not_changed: [{ id: 3, reason: "approved" }], check_figures: [] });
  assert.deepEqual(refineResultLines("rfp", t), ["Changed: Q1, Q2", "Not changed: Q3 (approved)"]);
});

test("a deck turn's lines name slides (AC-72c)", () => {
  const t = turn({ changed: [3], not_changed: [], check_figures: [2] });
  assert.deepEqual(refineResultLines("deck", t), ["Changed: Slide 3", "Check figures: Slide 2"]);
});

test("a turn that changed nothing has no lines", () => {
  assert.deepEqual(refineResultLines("deck", turn({})), []);
});

test("the composer on a Refine thread", () => {
  assert.deepEqual([REFINE_COPY.label, REFINE_COPY.submit, REFINE_COPY.sending, REFINE_COPY.help],
    ["Instruction", "Refine", "Refining…", "Enter sends the instruction; Shift+Enter adds a line."]);
});

test("a Refine selection names its document as <kind>/<doc_id>; the picker and unknown kinds name none", () => {
  assert.deepEqual(refineDoc("deck/r_1"), { kind: "deck", docId: "r_1" });
  assert.deepEqual(refineDoc("rfp/12"), { kind: "rfp", docId: "12" });
  for (const id of ["", "deck", "deck/", "memo/1", "/1"]) assert.equal(refineDoc(id), null, id);
});

test("Refine threads join the list, sorted by their newest turn", () => {
  const thread: RefineThread = { kind: "deck", doc_id: "R", title: "Deck: Climate review", status: "done", last_turn_at: "2026-11-22T12:00:00Z", turns: 1 };
  const exp = { id: "e", question: "q", label: "exploratory", created_at: "2026-11-22T11:00:00Z" } as Parameters<typeof threadRows>[2][number];
  const rows = threadRows([], [], [exp], [thread]);
  assert.deepEqual(rows.map((r) => [r.kind, r.id, r.title, r.status]), [["refine", "deck/R", "Deck: Climate review", "done"], ["exploration", "e", "q", "exploratory"]]);
});

test("the newest running turn, and the items marked changed", () => {
  assert.equal(refineRunning([turn({ turn_id: 1 }), turn({ turn_id: 2, status: "running" })])?.turn_id, 2);
  assert.equal(refineRunning([turn({})]), null);
  assert.deepEqual(refineChanged([turn({ changed: [1] }), turn({ changed: [2] })]), [2]);
  assert.deepEqual(refineChanged([turn({ changed: [1] }), turn({ changed: [2], status: "undone" })]), []);
  assert.deepEqual(refineChanged([]), []);
});

test("the RFP progress line", () => {
  assert.equal(refineProgress({ done: 1, total: 3 }), "Rewriting… 1 of 3");
  assert.equal(refineProgress({ done: 0, total: 0 }), "Rewriting…");
});

test("a refused write shows the API's detail, else Request failed (<status>)", () => {
  assert.equal(refineErrorText(409, { detail: "Nothing to undo." }), "Nothing to undo.");
  assert.equal(refineErrorText(500, null), "Request failed (500)");
  assert.equal(refineErrorText(422, { detail: [{ msg: "x" }] }), "Request failed (422)");
  assert.equal(refineErrorText("network", null), "Request failed (network)");
});

test("a slot overflows when its text needs more height than its box", () => {
  assert.equal(overflowing({ scrollHeight: 120, clientHeight: 100 }), true);
  assert.equal(overflowing({ scrollHeight: 100, clientHeight: 100 }), false);
});

test("a thread title is cut to 60 characters, prefix included", () => {
  assert.equal(refineTitle("deck", "x".repeat(70)), `Deck: ${"x".repeat(54)}`);
  assert.equal(refineTitle("rfp", "Nordic Pension Fund"), "RFP: Nordic Pension Fund");
});
