import test from "node:test";
import assert from "node:assert/strict";
import { fitZoom, readStoredZoom, stepZoom, wheelZoom } from "../src/lib/flowZoom.ts";

// Process flow viewer (docs/superpowers/specs/2026-11-23-process-flow-viewer.md).

test("ac27_zoom_rules", () => {
  assert.deepEqual(
    [fitZoom(1000, 7), fitZoom(2000, 7), fitZoom(300, 7), stepZoom(104, 1), stepZoom(104, -1), wheelZoom(195, -100), readStoredZoom("abc"), stepZoom(109.6, 1), stepZoom(100.4, -1)],
    [73, 100, 50, 110, 100, 200, 100, 120, 90],
  );
});

test("zoom limits and stored values", () => {
  assert.equal(stepZoom(200, 1), 200);
  assert.equal(stepZoom(50, -1), 50);
  assert.equal(stepZoom(100, 1), 110);
  assert.equal(stepZoom(100, -1), 90);
  assert.equal(wheelZoom(100, -100), 110);
  assert.equal(wheelZoom(100, 100), 90);
  assert.equal(wheelZoom(55, 100), 50);
  for (const raw of [null, "", "10", "500", "49.9", "NaN"]) assert.equal(readStoredZoom(raw), 100, String(raw));
  assert.equal(readStoredZoom("140"), 140);
  assert.equal(readStoredZoom("50"), 50);
  assert.equal(readStoredZoom("200"), 200);
});
