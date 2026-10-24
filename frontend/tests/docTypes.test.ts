import { test } from "node:test";
import assert from "node:assert/strict";
import { uploadText } from "../src/lib/docTypes.ts";

test("an identical upload says it was skipped", () => {
  assert.equal(uploadText("a.pdf", "Annual report", null), "a.pdf (Annual report): uploaded");
  assert.equal(uploadText("b.pdf", "Annual report", "a.pdf"), "b.pdf (Annual report): Duplicate of a.pdf, skipped");
});
