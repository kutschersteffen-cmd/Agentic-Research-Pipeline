import test from "node:test";
import assert from "node:assert/strict";
import { ageLabel, parseIntakeError, rowErrorText } from "../src/lib/holdings.ts";

test("ageLabel", () => {
  assert.equal(ageLabel(null), "No data");
  assert.equal(ageLabel(0), "today");
  assert.equal(ageLabel(1), "1 day");
  assert.equal(ageLabel(5), "5 days");
});

test("rowErrorText", () => {
  assert.equal(rowErrorText({ row: 3, column: "lei", message: "bad" }), "Row 3 (lei): bad");
  assert.equal(rowErrorText({ row: 3, column: null, message: "bad" }), "Row 3: bad");
  assert.equal(rowErrorText({ row: null, column: null, message: "missing header" }), "missing header");
});

test("parseIntakeError", () => {
  const e = parseIntakeError(new Error('422: {"message":"file rejected","errors":[{"row":3,"column":"lei","message":"x"}]}'));
  assert.equal(e.message, "file rejected");
  assert.deepEqual(e.errors, [{ row: 3, column: "lei", message: "x" }]);
  assert.deepEqual(parseIntakeError(new Error("413: File is larger")), { message: "413: File is larger", errors: [] });
});
