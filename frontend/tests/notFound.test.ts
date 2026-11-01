import test from "node:test";
import assert from "node:assert/strict";
import { notFoundLine } from "../src/lib/runs.ts";
import type { ExtractionRecord } from "../src/types.ts";

const rec = (reasons: (string | null)[]) =>
  ({ fields: reasons.map((r) => ({ not_found_reason: r })) }) as unknown as ExtractionRecord;

test("counts each reason and hides the zero ones", () => {  // AC-A3c
  const line = notFoundLine([rec(["no_passage", "no_passage", "passages_silent", null]), rec(["no_passage", "passages_silent"])]);
  assert.equal(line, "Not found: 3 no passage · 2 passages silent");
});

test("all three reasons", () => {
  assert.equal(notFoundLine([rec(["held", "no_passage", "passages_silent"])]), "Not found: 1 no passage · 1 passages silent · 1 held");
});

test("nothing when every count is 0", () => {
  assert.equal(notFoundLine([rec([null])]), null);
  assert.equal(notFoundLine([]), null);
});
