import test from "node:test";
import assert from "node:assert/strict";
import { canCosign, fieldItemKey, flaggedReasons, itemKeyOf } from "../src/lib/reviewKeys.ts";

const edit = { decision: "edit", user_id: "u1" };

test("canCosign: false for the same user, even an approver", () => {
  assert.equal(canCosign(edit, { user_id: "u1", role: "approver" }), false);
});

test("canCosign: false for a non-approver", () => {
  assert.equal(canCosign(edit, { user_id: "u2", role: "analyst" }), false);
});

test("canCosign: true for a different approver; false for non-edit or signed-out", () => {
  assert.equal(canCosign(edit, { user_id: "u2", role: "approver" }), true);
  assert.equal(canCosign({ decision: "approve", user_id: "u1" }, { user_id: "u2", role: "approver" }), false);
  assert.equal(canCosign(edit, null), false);
});

test("canCosign: false once co-signed", () => {
  assert.equal(canCosign({ ...edit, cosigned: true }, { user_id: "u2", role: "approver" }), false);
});

test("itemKeyOf returns the stored key for old and new rows", () => {
  assert.equal(itemKeyOf({ item_key: "C1" }), "C1");
  assert.equal(itemKeyOf({ item_key: "lei:X:rev:unspecified" }), "lei:X:rev:unspecified");
});

test("fieldItemKey carries the period, or unspecified, or the old company key", () => {
  const r = { company_id: "company", issuer_key: "lei:X" };
  assert.equal(fieldItemKey(r, { field_id: "f", period_end: "2024-12-31" }), "lei:X:f:2024-12-31");
  assert.equal(fieldItemKey(r, { field_id: "f" }), "lei:X:f:unspecified");
  assert.equal(fieldItemKey({ company_id: "company" }, { field_id: "f", period_end: "2024-12-31" }), "company:f");
});

test("flaggedReasons merges review and route reasons once each, in order", () => {
  assert.deepEqual(
    flaggedReasons({ reason_codes: ["not_grounded", "check_failed"], route_reasons: ["not_grounded", "check_failed", "first_audit_pending"] }),
    ["not_grounded", "check_failed", "first_audit_pending"],
  );
  assert.deepEqual(flaggedReasons({}), []);
});

import { decideBlock, decisionChoices, needsCitation } from "../src/lib/reviewKeys.ts";

test("decisionChoices and needsCitation by kind", () => {
  assert.ok(!decisionChoices("quarantined_document").includes("correct"));
  assert.deepEqual(decisionChoices("other"), []);
  assert.equal(decisionChoices("value").length, 4);
  assert.equal(needsCitation("identity"), false);
  assert.equal(needsCitation("value"), true);
});

test("decideBlock", () => {
  const analyst = { user_id: "u", name: "n", role: "analyst" as const };
  const approver = { ...analyst, role: "approver" as const };
  const base = { state: "pending" as const, escalated: false, decision: null };
  assert.equal(decideBlock(base, null), "Sign in as an analyst or approver to decide.");
  assert.equal(decideBlock(base, { ...analyst, role: "viewer" }), "Sign in as an analyst or approver to decide.");
  const dec = (mine: boolean) => ({ item_key: "k", decision: "approve" as const, decided_at: "", mine });
  assert.equal(decideBlock({ ...base, state: "first_done", decision: dec(true) }, analyst), "Waiting for a second reviewer.");
  assert.equal(decideBlock({ ...base, state: "first_done", decision: dec(false) }, analyst), null);
  assert.equal(decideBlock({ ...base, state: "disagreed" }, analyst), "Reviewers disagree; an approver decides.");
  assert.equal(decideBlock({ ...base, state: "disagreed" }, approver), null);
  assert.equal(decideBlock({ ...base, escalated: true }, analyst), "Escalated; an approver decides.");
});
