import test from "node:test";
import assert from "node:assert/strict";
import { NAMES, rankRanges, sampleValues, tierOf } from "../src/pages/lab/rankLadderData.ts";

test("tierOf maps ranks to tier indexes at the boundaries", () => {
  assert.deepEqual([1, 5, 6, 12, 13, 19, 20, 25].map(tierOf), [0, 0, 1, 1, 2, 2, 3, 3]);
});

test("a single spec's ranks are a permutation, so identical specs give point ranges", () => {
  const values = sampleValues();
  const same = rankRanges(values, [3, 3, 2, 2, 2], [[1, 1, 1, 1, 1], [1, 1, 1, 1, 1]]);
  assert.equal(same.length, NAMES.length);
  assert.deepEqual([...same.map((e) => e.lo)].sort((a, b) => a - b), NAMES.map((_, i) => i + 1));
  assert.ok(same.every((e) => e.lo === e.hi && !e.unstable && !e.hatchLo && !e.hatchHi));
});

test("ranges are ordered best-first and unstable means lo and hi sit in different tiers", () => {
  const out = rankRanges(sampleValues(), [3, 3, 2, 2, 2]);
  for (let i = 1; i < out.length; i++) assert.ok(out[i - 1].lo + out[i - 1].hi <= out[i].lo + out[i].hi);
  for (const e of out) {
    assert.ok(e.lo <= e.hi);
    assert.equal(e.unstable, tierOf(e.lo) !== tierOf(e.hi));
  }
});

test("zero weights collapse to index-order ranks", () => {
  const out = rankRanges(sampleValues(), [0, 0, 0, 0, 0]);
  assert.ok(out.every((e) => e.lo === e.index + 1 && e.hi === e.index + 1));
});
