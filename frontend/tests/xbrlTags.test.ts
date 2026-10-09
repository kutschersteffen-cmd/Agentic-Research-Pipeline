import test from "node:test";
import assert from "node:assert/strict";
import {
  ariaSort,
  canRetryFetch,
  formatFactValue,
  keyLabel,
  safeHref,
  nextSort,
  periodLabel,
  rangeLabel,
  reportText,
  secFilingUrl,
  statusText,
  sortVerifyRows,
  tagQuery,
  toleranceFraction,
  toggleTag,
  verifyDetailText,
  verifyMapping,
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

test("toleranceFraction converts a percentage and rejects out-of-range or non-numbers", () => {
  assert.equal(toleranceFraction("0.5"), 0.005);
  assert.equal(toleranceFraction(" 2,5 "), 0.025);
  assert.equal(toleranceFraction("0"), 0);
  assert.equal(toleranceFraction("100"), 1);
  for (const bad of ["", "101", "-1", "abc", "1e2", "0.5%"]) assert.equal(toleranceFraction(bad), null);
});

test("verifyMapping needs at least one field id", () => {
  assert.equal(verifyMapping(" ", ""), null);
  assert.deepEqual(verifyMapping(" rev ", ""), { revenue: "rev" });
  assert.deepEqual(verifyMapping("rev", "cx"), { revenue: "rev", capex: "cx" });
});

test("sortVerifyRows puts mismatches, then missing, before matches", () => {
  const r = (company_id: string, outcome: string, fiscal_year = 2024, metric = "revenue") => ({ company_id, outcome, fiscal_year, metric });
  const sorted = sortVerifyRows([r("b", "match"), r("a", "missing_in_xbrl"), r("c", "mismatch"), r("a", "missing_in_run"), r("a", "mismatch", 2023)]);
  assert.deepEqual(sorted.map((x) => `${x.company_id}:${x.outcome}:${x.fiscal_year}`), [
    "a:mismatch:2023",
    "c:mismatch:2024",
    "a:missing_in_run:2024",
    "a:missing_in_xbrl:2024",
    "b:match:2024",
  ]);
  assert.equal(verifyDetailText("unit"), "Units differ");
  assert.equal(verifyDetailText(""), "–");
});

test("retry is offered unless a run is in progress or fully done", () => {
  const run = (status: string, failed_count = 0, completed_count = 5, company_count = 5) => ({ status, failed_count, completed_count, company_count });
  assert.equal(canRetryFetch(null, false), false);
  assert.equal(canRetryFetch(run("completed"), false), false);
  assert.equal(canRetryFetch(run("partially_completed", 2, 3), false), true);
  assert.equal(canRetryFetch(run("failed", 0, 0), false), true);
  assert.equal(canRetryFetch(run("cancelled"), false), true);
  assert.equal(canRetryFetch(run("completed", 0, 3), false), true); // never reached two companies
  assert.equal(canRetryFetch(run("running", 0, 1), false), false);
  assert.equal(canRetryFetch(run("pending", 0, 0), false), false);
  assert.equal(canRetryFetch(run("running", 0, 1), true), true); // stalled
  assert.equal(canRetryFetch(run("completed"), true), false);
});

test("keyLabel names the market's company key; statusText explains no_lei", () => {
  assert.equal(keyLabel("sec"), "CIK");
  assert.equal(keyLabel("esef"), "LEI");
  assert.equal(statusText("no_lei"), "No LEI in the universe row");
});

test("safeHref passes only http(s) URLs", () => {
  assert.equal(safeHref("https://x.eu/p.zip"), "https://x.eu/p.zip");
  assert.equal(safeHref("http://x.eu/p.zip"), "http://x.eu/p.zip");
  assert.equal(safeHref("HTTPS://x.eu/p.zip"), "HTTPS://x.eu/p.zip");
  assert.equal(safeHref("javascript:alert(1)"), null);
  assert.equal(safeHref("data:text/html,x"), null);
  assert.equal(safeHref(null), null);
});

test("statusText names where not_found looked, by market when known", () => {
  assert.equal(statusText("not_found", "sec"), "Not found at the SEC");
  assert.equal(statusText("not_found", "esef"), "Not found in the ESEF filing index");
  assert.equal(statusText("not_found"), "Not found at the SEC or in the ESEF filing index");
  assert.equal(statusText("ok", "esef"), "Facts fetched");
});
