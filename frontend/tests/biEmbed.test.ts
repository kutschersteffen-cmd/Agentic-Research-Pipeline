import test from "node:test";
import assert from "node:assert/strict";
import { designRequestBody, embedErrorText, embedUrlFor, pickDefaultDashboard } from "../src/lib/biEmbed.ts";

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

const dash = (id: number, slug: string, published = true) => ({ id, slug, title: slug, published });

test("pickDefaultDashboard prefers arp-risk-exposure", () => {
  const items = [dash(1, "arp-a"), dash(2, "arp-risk-exposure"), dash(3, "arp-z")];
  assert.equal(pickDefaultDashboard(items)?.id, 2);
});

test("pickDefaultDashboard falls back to the first item", () => {
  assert.equal(pickDefaultDashboard([dash(4, "arp-b"), dash(5, "arp-c")])?.id, 4);
});

test("pickDefaultDashboard returns null for an empty list", () => {
  assert.equal(pickDefaultDashboard([]), null);
});

test("embedErrorText says a 403/404 dashboard is gone and strips the status prefix otherwise", () => {
  assert.equal(embedErrorText("403: not an arp- dashboard"), "This dashboard is no longer available here.");
  assert.equal(embedErrorText("404: dashboard 9 not found"), "This dashboard is no longer available here.");
  assert.equal(embedErrorText("502: Superset is unreachable"), "Superset is unreachable");
});
