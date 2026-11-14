import test from "node:test";
import assert from "node:assert/strict";
import { objectiveRows } from "../src/lib/engagement.ts";
import type { Objective } from "../src/types.ts";

const obj = (o: Partial<Objective> = {}): Objective => ({
  objective_id: "obj_1", description: "Publish a TCFD report", objective_type: "transparency",
  status: "in_progress", result: null, source: "app", ...o,
});

test("no objectives gives no rows", () => {
  assert.deepEqual(objectiveRows({}), []);
  assert.deepEqual(objectiveRows({ objectives: [] }), []);
});

test("row carries description, type, status and a dash for an open result", () => {
  assert.deepEqual(objectiveRows({ objectives: [obj()], data_source: "app" }), [
    { description: "Publish a TCFD report", type: "transparency", status: "in progress", result: "—", demo: false },
  ]);
});

test("closed objective shows its result", () => {
  const [r] = objectiveRows({ objectives: [obj({ status: "closed", result: "partially_achieved" })] });
  assert.equal(r.result, "partially achieved");
});

test("demo when the issue or the objective is demo-sourced", () => {
  for (const s of ["mock_voice_seed", "npx_urth_demo"]) {
    assert.equal(objectiveRows({ objectives: [obj()], data_source: s })[0].demo, true);
    assert.equal(objectiveRows({ objectives: [obj({ source: s })], data_source: "app" })[0].demo, true);
  }
});
