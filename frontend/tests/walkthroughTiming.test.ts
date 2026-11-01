import { test } from "node:test";
import assert from "node:assert/strict";
import { formatSeconds, stepNode, stepTiming, timingTotal, usageText } from "../src/lib/walkthrough.ts";
import type { Walkthrough } from "../src/types.ts";

// step-timing spec, AC-9 to AC-18
const call = (i: number, o: number, c: number) => ({ model: "m", prompt_version: "v", answer: {}, input_tokens: i, output_tokens: o, cost_usd: c });
const w = (o: Partial<Walkthrough>) => ({ run_type: "extraction", extractor: null, verifier: null, adjudicator: null, vision: null, seconds: {}, ...o }) as unknown as Walkthrough;

test("time format", () => {  // AC-9
  assert.deepEqual([0.004, 1.234, 12.34].map(formatSeconds), ["< 0.01 s", "1.23 s", "12.3 s"]);
});

test("usage format", () => {  // AC-10, AC-11, AC-16
  assert.equal(usageText(call(3410, 212, 0.01234)), "3,410 → 212 tokens · $0.0123");
  assert.ok(usageText(call(10, 1, 0))!.endsWith("· cached"));
  assert.ok(usageText(call(10, 1, 0.00004))!.endsWith("· cached"));
  assert.equal(usageText({ model: "m", prompt_version: "v", answer: {} }), null);
  assert.equal(usageText(call(0, 0, 0)), null);
});

test("total", () => {  // AC-12, AC-13
  assert.equal(timingTotal(w({ seconds: { extract: 1.5, verify: 0.5 }, extractor: call(1000, 100, 0.01), verifier: call(1000, 100, 0.01) })),
    "2.00 s · 2,200 tokens · $0.0200");
  assert.equal(timingTotal(w({})), null);
});

test("step → node", () => {  // AC-14, AC-15
  assert.equal(stepTiming(w({ seconds: { gather_evidence: 0.2 } }), "Find evidence"), "0.20 s");
  const nodes: Record<string, string | null> = {
    "Tagged data first": "try_tagged", "Find evidence": "gather_evidence", Extract: "extract", Verify: "verify",
    "Verify, blind": "verify", Adjudicate: "adjudicate", "Ground every quote": "aggregate",
    "Auto-corrections": null, Checks: null, Route: null, "Combine into one record": null,
  };
  for (const [step, node] of Object.entries(nodes)) assert.equal(stepNode(step), node, step);
});

test("old traces and financials show nothing", () => {  // AC-17, AC-18
  const old = w({ extractor: { model: "m", prompt_version: "v", answer: {} } });
  for (const s of ["Find evidence", "Extract", "Verify"]) assert.equal(stepTiming(old, s), "");
  const fin = w({ run_type: "financials", seconds: { extract: 1 }, extractor: call(10, 1, 0.1) });
  assert.equal(stepTiming(fin, "Extract"), "");
  assert.equal(timingTotal(fin), null);
});
