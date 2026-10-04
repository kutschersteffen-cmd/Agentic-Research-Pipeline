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
