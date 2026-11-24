import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// client.ts cannot be imported under node:test, so read the call's source.
test("approveSpecDraft sends an empty JSON object as the body", () => {
  const src = readFileSync(new URL("../src/api/client.ts", import.meta.url), "utf8");
  const call = src.slice(src.indexOf("approveSpecDraft:"), src.indexOf("uploadPriceDataset:"));
  assert.ok(call.includes('/approve`'), call);
  assert.ok(call.includes("body: JSON.stringify({})"), call);
});
