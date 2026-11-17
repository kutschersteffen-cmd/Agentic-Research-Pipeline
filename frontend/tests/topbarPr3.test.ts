import test from "node:test";
import assert from "node:assert/strict";
import { flowTrack } from "../src/lib/workspaceCard.ts";

// App-wide top bar, PR 3 (docs/superpowers/specs/2026-11-15-app-wide-top-bar-design.md, AC-33..AC-42).

test("pr3_ac39_flow_track", () => {
  assert.deepEqual(flowTrack(["done", "idle", "done", "now", "idle"]), { reached: 2, runInto: [false, false, false, true, false] });
  assert.deepEqual(flowTrack(["now", "idle"]), { reached: -1, runInto: [true, false] });
  assert.deepEqual(flowTrack(["idle", "wait"]), { reached: -1, runInto: [false, false] });
  assert.deepEqual(flowTrack([]), { reached: -1, runInto: [] });
});
