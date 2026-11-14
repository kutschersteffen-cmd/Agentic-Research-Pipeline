import test from "node:test";
import assert from "node:assert/strict";
import { isDemo } from "../src/lib/engagement.ts";

test("demo when the issue or the objective is demo-sourced", () => {
  for (const s of ["mock_voice_seed", "npx_urth_demo"]) {
    assert.equal(isDemo({ data_source: s }, { source: "app" }), true);
    assert.equal(isDemo({ data_source: "app" }, { source: s }), true);
  }
});

test("not demo for app or missing sources", () => {
  assert.equal(isDemo({ data_source: "app" }, { source: "app" }), false);
  assert.equal(isDemo({}, {}), false);
});
