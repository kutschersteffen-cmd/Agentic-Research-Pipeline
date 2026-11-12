import { test } from "node:test";
import assert from "node:assert/strict";
import { lastRunText, presetCountText, walkTalkLine } from "../src/lib/argusFlow.ts";

// showcase-stewardship-fixes AC-52..AC-55, AC-58, AC-63
const run = (status: string, minutes: number, companies: number, cost: number | null, created = "2026-11-10T09:00:00+00:00") => ({
  status, created_at: created, updated_at: new Date(Date.parse(created) + minutes * 60000).toISOString(),
  company_count: companies, estimated_cost_usd: cost,
} as Parameters<typeof lastRunText>[0][number]);

test("the latest finished run of the template is stated as it was", () => {
  assert.equal(lastRunText([run("completed", 13, 1, 8.58)]), "The last run of this template took 13 min and $8.58 for 1 company.");
  assert.equal(lastRunText([run("partially_completed", 75 + 20 / 60, 2, 20)]), "The last run of this template took 75 min and $20.00 for 2 companies.");
  assert.equal(lastRunText([run("completed", 13, 1, null)]), "The last run of this template took 13 min for 1 company; its cost was not recorded.");
  assert.equal(lastRunText([run("completed", 0.2, 1, 1)]), "The last run of this template took 1 min and $1.00 for 1 company.");
  assert.equal(
    lastRunText([run("completed", 13, 1, 8.58, "2026-11-01T09:00:00+00:00"), run("completed", 30, 3, 9, "2026-11-05T09:00:00+00:00")]),
    "The last run of this template took 30 min and $9.00 for 3 companies.",
  );
});

test("no finished run of the template says time and cost are not known", () => {
  const none = "No earlier run of this template yet, so time and cost are not known. Try it on 1 company first: the run shows both.";
  assert.equal(lastRunText([run("failed", 13, 1, 8.58)]), none);
  assert.equal(lastRunText([]), none);
});

test("the transition-plan template counts indicators apart from supporting figures", () => {
  assert.equal(presetCountText({ preset_id: "transition_plan_indicators", field_count: 72 }, 64), "64 indicators + 8 supporting figures");
  assert.equal(presetCountText({ preset_id: "green_revenue", field_count: 5 }, 64), "5 fields");
});

test("a company's line counts Yes answers in all and by walk and talk", () => {
  const indicators = [
    { identifier: "W1", walk_or_talk: "walk" }, { identifier: "W2", walk_or_talk: "walk" }, { identifier: "W3", walk_or_talk: "walk" },
    { identifier: "T1", walk_or_talk: "talk" }, { identifier: "T2", walk_or_talk: "talk" },
  ];
  const f = (field_name: string, value: boolean | null, value_state: "found" | "not_found" = "found") => ({ field_id: field_name, field_name, value, value_state });
  const record = { fields: [f("W1", true), f("W2", true), f("W3", false), f("T1", true), f("T2", null, "not_found"), f("capex_total", true)] } as never;
  assert.equal(walkTalkLine(record, indicators), "Disclosed 3 of 5 · Walk 2 of 3 · Talk 1 of 2");
});
