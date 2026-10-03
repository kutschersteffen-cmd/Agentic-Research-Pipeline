import test from "node:test";
import assert from "node:assert/strict";
import { canCosign, itemKeyOf } from "../src/lib/reviewKeys.ts";

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
