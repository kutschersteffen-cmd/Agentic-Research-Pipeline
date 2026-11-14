import test from "node:test";
import assert from "node:assert/strict";
import { canSaveResult, checkLine, engagementCounts, engagementLine, evidenceText, foundLine, issueTopics } from "../src/lib/engagement.ts";

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

test("issueTopics keeps one engagement's topics in the API's order", () => {
  const topics = [
    { topic_id: "t3", engagement_id: "e1" },
    { topic_id: "t2", engagement_id: "e2" },
    { topic_id: "t1", engagement_id: "e1" },
  ];
  assert.deepEqual(issueTopics(topics, "e1").map((t) => t.topic_id), ["t3", "t1"]);
  assert.deepEqual(issueTopics(topics, "e9"), []);
});

test("checkLine spells out singular and plural, and the no-documents case", () => {
  assert.equal(checkLine({ documents: 1, suggestions: 1, unclear: 0 }), "Checked 1 document: 1 new suggestion, 0 unclear.");
  assert.equal(checkLine({ documents: 5, suggestions: 0, unclear: 2 }), "Checked 5 documents: 0 new suggestions, 2 unclear.");
  assert.equal(checkLine({ documents: 0, suggestions: 0, unclear: 0 }), "No documents on file for this company.");
});

test("foundLine counts suggestions", () => {
  assert.equal(foundLine(1), "Found 1 suggestion.");
  assert.equal(foundLine(0), "Found 0 suggestions.");
});

test("evidenceText leaves out the page, or the title, when unknown", () => {
  const quote = "The board formed a climate committee in March 2026.";
  assert.equal(evidenceText({ doc_title: "AR2026.txt", page: null, quote }), `AR2026.txt: "${quote}"`);
  assert.equal(evidenceText({ doc_title: "AR 2026.pdf", page: 4, quote }), `AR 2026.pdf, page 4: "${quote}"`);
  assert.equal(evidenceText({ doc_title: null, page: null, quote }), `"${quote}"`);
});

test("Save result needs an influence level unless the result is abandoned", () => {
  assert.equal(canSaveResult("achieved", "", "Committee named"), false);
  assert.equal(canSaveResult("achieved", "3", "Committee named"), true);
  assert.equal(canSaveResult("abandoned", "", "Company sold the unit"), true);
  assert.equal(canSaveResult("achieved", "3", "  "), false);
  assert.equal(canSaveResult("", "3", "x"), false);
});
