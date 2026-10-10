import test from "node:test";
import assert from "node:assert/strict";
import { fieldItemKey, flaggedReasons } from "../src/lib/reviewKeys.ts";

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

import { agreeBody, decideBlock, decisionChoices, needsCitation } from "../src/lib/reviewKeys.ts";

test("decisionChoices and needsCitation by kind", () => {
  assert.ok(!decisionChoices("quarantined_document").includes("correct"));
  assert.deepEqual(decisionChoices("other"), []);
  assert.deepEqual(decisionChoices("other", "theme"), []);
  assert.deepEqual(decisionChoices("other", "extraction"), ["approve", "reject", "escalate"]);
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

test("agreeBody resubmits a visible first correction", () => {
  const cit = { doc_id: "d1", doc_type: "annual_report" as const, quote: "1,100", span_text: "Scope 1  1,100", grounded: true };
  const first = {
    item_key: "k", decision: "correct" as const, reason_code: "wrong_value", corrected_value: { value: 1100 },
    correction_citation: cit, comment: "note", decided_at: "", mine: false,
  };
  const ctx = { blind: false, decisions: [first] };
  assert.deepEqual(agreeBody("value", "first_done", ctx), {
    decision: "correct", reason_code: "wrong_value", corrected_value: { value: 1100 },
    correction_citation: { doc_id: "d1", doc_type: "annual_report", quote: "Scope 1  1,100" }, comment: "note",
  });
  assert.equal(agreeBody("value", "first_done", { blind: true, decisions: [] }), null);
  assert.equal(agreeBody("value", "pending", ctx), null);
  assert.equal(agreeBody("value", "first_done", { blind: false, decisions: [{ ...first, mine: true }] }), null);
  assert.equal(agreeBody("value", "first_done", { blind: false, decisions: [{ ...first, decision: "edit" as const }] }), null);
  assert.equal(agreeBody("identity", "first_done", ctx)?.correction_citation, null);
});

test("security items: labelled, decidable four ways, no citation", async () => {
  const { ITEM_KIND_LABEL, decisionChoices, needsCitation } = await import("../src/lib/reviewKeys.ts");
  assert.equal(ITEM_KIND_LABEL.security, "Security");
  assert.ok(decisionChoices("security").includes("correct"));
  assert.equal(decisionChoices("security").length, 4);
  assert.equal(needsCitation("security"), false);
});
