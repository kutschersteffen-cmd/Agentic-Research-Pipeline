import { test } from "node:test";
import assert from "node:assert/strict";
import {
  castBannerText,
  castDialogText,
  castFailedText,
  emptyBallotsText,
  isRoutine,
  missingCoSignText,
  recordedText,
} from "../src/lib/votingWording.ts";
import { unlistedText } from "../src/lib/engagement.ts";

// showcase-stewardship-fixes PR B
const vote = (type: string, text: string, rec: Record<string, unknown> | null) =>
  ({
    proposal: { type, resolution_text: text },
    policy_recommendation: rec && { vote: "for", rationale: "", engagement_alignment_flag: false, ...rec },
  }) as never;
const rule = (confidence: number) => ({ policy_rule_id: "rule_routine_management_proposal", confidence });

test("say-on-pay is never routine (AC-123)", () => {
  assert.equal(isRoutine(vote("say_on_pay", "Approve executive pay", rule(1))), false);
});

test("redomiciliation is never routine, any spelling (AC-124, AC-125)", () => {
  for (const text of [
    "Approve the redomiciliation of the Company to Delaware",
    "REINCORPORATION IN NEVADA",
    "Change of the jurisdiction of incorporation",
    "Re-domiciliation to Ireland",
  ]) {
    assert.equal(isRoutine(vote("other", text, rule(1))), false, text);
  }
  assert.equal(isRoutine(vote("other", "Amend the articles of association", rule(1))), true);
});

test("low confidence and model-judged recommendations are not routine (AC-126, AC-127, AC-128)", () => {
  assert.equal(isRoutine(vote("capital_action", "Routine item.", rule(0.59))), false);
  assert.equal(isRoutine(vote("capital_action", "Routine item.", rule(0.6))), true);
  assert.equal(isRoutine(vote("director_election", "Elect A", { policy_rule_id: null, confidence: 0.95 })), false);
  assert.equal(isRoutine(vote("capital_action", "Routine item.", rule(1))), true);
  assert.equal(isRoutine(vote("capital_action", "Routine item.", { ...rule(1), engagement_alignment_flag: true })), false);
  assert.equal(isRoutine(vote("capital_action", "Routine item.", null)), false);
});

test("the cast wording says what is recorded (AC-116..121)", () => {
  assert.equal(
    castDialogText(5),
    "This records 5 votes as voting instructions, one file per vote, to be entered on the ballot platform by hand. Nothing is sent to a ballot platform from here. Recorded votes cannot be recalled from here.",
  );
  assert.equal(
    castDialogText(1),
    "This records 1 vote as a voting instruction, in its own file, to be entered on the ballot platform by hand. Nothing is sent to a ballot platform from here. Recorded votes cannot be recalled from here.",
  );
  const banner = castBannerText(5, "Ana", "12/11/2026, 10:00:00");
  assert.ok(banner.startsWith("5 votes recorded as voting instructions by Ana at"));
  assert.ok(banner.endsWith("The instruction reference is shown on each proposal below."));
  assert.equal(recordedText("conf_abc"), "Recorded · instruction ref conf_abc");
  assert.equal(missingCoSignText(2), "2 flagged votes have no co-sign and will be refused when the votes are recorded.");
  assert.equal(missingCoSignText(1), "1 flagged vote has no co-sign and will be refused when the votes are recorded.");
  assert.equal(castFailedText("400: X"), "Recording the votes failed: X. Nothing was recorded; try again.");
});

test("an empty ballot list says why, by run status (AC-130..133)", () => {
  const run = (status: string, done: number) => ({ status, company_count: 5, completed_count: done, failed_count: 0 }) as never;
  assert.equal(
    emptyBallotsText(run("running", 2)),
    "This voting run is still in progress (2 of 5 companies done). Ballots appear here as they are ready.",
  );
  assert.equal(
    emptyBallotsText(run("pending", 0)),
    "This voting run is still in progress (0 of 5 companies done). Ballots appear here as they are ready.",
  );
  assert.equal(
    emptyBallotsText(run("failed", 0)),
    "This voting run stopped before any ballot was ready (status: failed). Run History shows why.",
  );
  assert.equal(
    emptyBallotsText(run("cancelled", 0)),
    "This voting run stopped before any ballot was ready (status: cancelled). Run History shows why.",
  );
  const done = "No ballots in this run yet: none of its companies has a proxy statement for an upcoming meeting. Start a new voting run once one is filed.";
  assert.equal(emptyBallotsText(run("completed", 5)), done);
  assert.equal(emptyBallotsText(null), done);
});

test("signals for companies not in the list are counted (AC-110, AC-111)", () => {
  assert.equal(unlistedText(1, ["C2"]), "1 signal skipped: its company is not in the list (C2).");
  assert.equal(unlistedText(3, ["C2", "C3"]), "3 signals skipped: their companies are not in the list (C2, C3).");
});
