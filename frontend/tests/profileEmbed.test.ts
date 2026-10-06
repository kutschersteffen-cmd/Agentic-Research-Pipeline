import test from "node:test";
import assert from "node:assert/strict";
import { profileEmbedParams } from "../src/lib/biEmbed.ts";

test("no issuer: the guest token is not restricted", () => {
  assert.deepEqual(profileEmbedParams(null), {});
  assert.deepEqual(profileEmbedParams(""), {});
});

test("an issuer is sent as company_id for the server's RLS clause", () => {
  assert.deepEqual(profileEmbedParams("abc"), { company_id: "abc" });
});

test("a quote in the id reaches the server intact; the client never builds SQL", () => {
  const body = JSON.stringify({ dashboard_id: "7", ...profileEmbedParams("O'Neil' OR '1'='1") });
  assert.equal(JSON.parse(body).company_id, "O'Neil' OR '1'='1");
  assert.ok(!/clause|rls/i.test(body));
});
