import test from "node:test";
import assert from "node:assert/strict";
import { engagementCounts, engagementLine } from "../src/lib/engagement.ts";

const issue = (status: string, escalation_stage: string) => ({ status, escalation_stage }) as never;

test("engagementCounts tells open, stalled and escalated apart", () => {
  const records = [
    {
      issues: [
        issue("open", "private_engagement"),
        issue("open", "joint_engagement"),
        issue("stalled", "joint_engagement"),
        issue("resolved", "joint_engagement"),
        issue("closed", "joint_engagement"),
      ],
    },
  ];
  const counts = engagementCounts(records);
  assert.deepEqual(counts, { open: 3, stalled: 1, escalated: 2 });
  assert.equal(engagementLine(counts), "Engagement · 3 open · 1 stalled · 2 escalated");
});

test("engagementCounts is all zero with no records or no issues", () => {
  assert.deepEqual(engagementCounts([]), { open: 0, stalled: 0, escalated: 0 });
  assert.deepEqual(engagementCounts([{ issues: [] }]), { open: 0, stalled: 0, escalated: 0 });
});

test("an unknown escalation stage counts as escalated while the issue is open", () => {
  assert.deepEqual(engagementCounts([{ issues: [issue("open", "some_new_stage")] }]), { open: 1, stalled: 0, escalated: 1 });
});

test("engagementLine never shows a zero nobody measured", () => {
  assert.equal(engagementLine(null), "Engagement · — open · — stalled · — escalated");
  assert.equal(engagementLine("error"), "Engagement · counts unavailable");
});
