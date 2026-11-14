import test from "node:test";
import assert from "node:assert/strict";
import { overflowing, pollMs, progressLine, refineTarget, resultLines, trimHistory } from "../src/lib/refine.ts";
import type { RefineTurn } from "../src/types.ts";

const turn = (over: Partial<RefineTurn>): RefineTurn => ({
  id: 1, status: "done", reply: "", done: 0, total: 0, changed: [], not_changed: [], check_figures: [], error: null, ...over,
});

test("resultLines lists changed, not changed with reasons, and figures to check (AC-42)", () => {
  assert.deepEqual(
    resultLines(turn({ changed: [1, 2], not_changed: [{ id: 3, reason: "approved" }], check_figures: [2] })),
    ["Changed: Q1, Q2", "Not changed: Q3 (approved)", "Check figures: Q2"],
  );
});

test("resultLines omits empty parts and gives each not-changed item its own line", () => {
  assert.deepEqual(resultLines(turn({})), []);
  assert.deepEqual(
    resultLines(turn({ not_changed: [{ id: 3, reason: "approved" }, { id: null, reason: "no such question" }] })),
    ["Not changed: Q3 (approved)", "Not changed: (no question named) (no such question)"],
  );
});

test("resultLines names deck ids as slides", () => {
  assert.deepEqual(
    resultLines(turn({ changed: [3], not_changed: [{ id: 2, reason: "no such slot" }], check_figures: [2] }), "deck"),
    ["Changed: Slide 3", "Not changed: Slide 2 (no such slot)", "Check figures: Slide 2"],
  );
});

test("progressLine counts while running, else nothing (AC-41)", () => {
  assert.equal(progressLine(turn({ status: "running", done: 1, total: 3 })), "1 of 3");
  assert.equal(progressLine(turn({ status: "running", done: 0, total: 0 })), null);
  assert.equal(progressLine(turn({ status: "done", done: 3, total: 3 })), null);
});

test("pollMs: 1 s while a turn runs, else 3 s", () => {
  assert.equal(pollMs(true), 1000);
  assert.equal(pollMs(false), 3000);
});

test("trimHistory keeps the 5 newest turns", () => {
  const h = Array.from({ length: 7 }, (_, i) => ({ message: `m${i}`, reply: `r${i}` }));
  assert.deepEqual(trimHistory(h).map((x) => x.message), ["m2", "m3", "m4", "m5", "m6"]);
  assert.equal(trimHistory(h.slice(0, 2)).length, 2);
});

test("overflowing: content taller than its box", () => {
  assert.equal(overflowing({ scrollHeight: 300, clientHeight: 200 } as HTMLElement), true);
  assert.equal(overflowing({ scrollHeight: 200, clientHeight: 200 } as HTMLElement), false);
});

test("refineTarget reads rfp and report, and ignores an rfp that is not a number", () => {
  assert.deepEqual(refineTarget(new URLSearchParams("rfp=3")), { rfp: 3, report: null });
  assert.deepEqual(refineTarget(new URLSearchParams("report=rpt_1")), { rfp: null, report: "rpt_1" });
  assert.deepEqual(refineTarget(new URLSearchParams("rfp=abc")), { rfp: null, report: null });
});
