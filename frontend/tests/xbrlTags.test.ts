import test from "node:test";
import assert from "node:assert/strict";
import {
  ariaSort,
  formatFactValue,
  nextSort,
  periodLabel,
  rangeLabel,
  reportText,
  secFilingUrl,
  statusText,
  tagQuery,
  toggleTag,
  verifySummary,
} from "../src/lib/xbrlTags.ts";

test("toggleTag adds, removes and never duplicates", () => {
  assert.deepEqual(toggleTag(["a"], "b"), ["a", "b"]);
  assert.deepEqual(toggleTag(["a", "b", "c"], "b"), ["a", "c"]);
  assert.deepEqual(toggleTag(toggleTag([], "a"), "a"), []);
  assert.deepEqual(toggleTag(["a", "a"], "b"), ["a", "b"]);
});

test("tagQuery encodes only the set keys", () => {
  assert.equal(tagQuery({ q: "rev enue", seenOnly: true }), "?q=rev%20enue&seen_only=true");
  assert.equal(tagQuery({}), "");
  assert.equal(tagQuery({ offset: 0, limit: 50 }), "?offset=0&limit=50");
});

test("status and report texts", () => {
  assert.notEqual(statusText("no_cik"), "");
  assert.notEqual(statusText("not_found"), "");
  assert.notEqual(statusText("no_cik"), statusText("not_found"));
  assert.notEqual(reportText("none"), "");
});

test("verifySummary always has four outcomes", () => {
  assert.deepEqual(verifySummary([]), { match: 0, mismatch: 0, missing_in_run: 0, missing_in_xbrl: 0 });
  assert.deepEqual(verifySummary([{ outcome: "match" }, { outcome: "match" }, { outcome: "mismatch" }]), {
    match: 2, mismatch: 1, missing_in_run: 0, missing_in_xbrl: 0,
  });
});

test("formatFactValue", () => {
  assert.equal(formatFactValue(1200000, "USD"), "1,200,000");
  assert.equal(formatFactValue(0.12345678, "pure"), "0.1235");
  assert.equal(formatFactValue(-1500, "USD"), "-1,500");
  assert.equal(formatFactValue(1.5, "USD"), "1.5");
});

test("periodLabel", () => {
  assert.equal(periodLabel(null, "2024-10-18"), "as of 2024-10-18");
  assert.equal(periodLabel("2023-10-01", "2024-09-28"), "2023-10-01 to 2024-09-28");
});

test("secFilingUrl", () => {
  assert.equal(
    secFilingUrl("0000320193", "0000320193-24-000123"),
    "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/",
  );
});

test("nextSort and ariaSort", () => {
  assert.deepEqual(nextSort({ key: "a", order: "asc" }, "a"), { key: "a", order: "desc" });
  assert.deepEqual(nextSort({ key: "a", order: "desc" }, "a"), { key: "a", order: "asc" });
  assert.deepEqual(nextSort({ key: "a", order: "desc" }, "b"), { key: "b", order: "asc" });
  assert.equal(ariaSort({ key: "a", order: "asc" }, "a"), "ascending");
  assert.equal(ariaSort({ key: "a", order: "desc" }, "a"), "descending");
  assert.equal(ariaSort({ key: "a", order: "asc" }, "b"), "none");
});

test("rangeLabel shows the visible rows and the total", () => {
  assert.equal(rangeLabel(20, 20, 1234), "21–40 of 1,234");
  assert.equal(rangeLabel(0, 3, 3), "1–3 of 3");
  assert.equal(rangeLabel(0, 0, 0), "0 of 0");
});
