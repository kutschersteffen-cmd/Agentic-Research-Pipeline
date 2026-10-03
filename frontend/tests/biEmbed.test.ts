import test from "node:test";
import assert from "node:assert/strict";
import { designRequestBody, embedUrlFor } from "../src/lib/biEmbed.ts";

test("designRequestBody trims the brief", () => {
  assert.deepEqual(designRequestBody("  exposure by sector \n"), { brief: "exposure by sector" });
});

test("embedUrlFor returns null when dashboard_id is null", () => {
  assert.equal(embedUrlFor({ dashboard_id: null }, "0b5c-uuid"), null);
});

test("embedUrlFor returns null until the embedded uuid is known", () => {
  assert.equal(embedUrlFor({ dashboard_id: 7 }, null), null);
});

test("embedUrlFor is the SDK's iframe url: domain + /embedded/ + embedded uuid, not the numeric id", () => {
  assert.equal(
    embedUrlFor({ dashboard_id: 7 }, "0b5c-uuid", "http://superset.test:8088/"),
    "http://superset.test:8088/embedded/0b5c-uuid",
  );
});
