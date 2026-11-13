import { test } from "node:test";
import assert from "node:assert/strict";
import {
  companiesLocked, docTypeLabel, identityPolls, identityStatus, newFieldId, plainError, releaseQuestion, stepFromUrl,
} from "../src/lib/argusFlow.ts";
import { argusRows, companiesSummary, filterLine } from "../src/lib/argusStart.ts";
import type { ArgusDraft } from "../src/types.ts";

// showcase-argus-fixes, PR 2: start page and steps 1 to 3.

test("AC-85: a stored type shows the dropdown's label; one without a label shows as stored", () => {
  assert.equal(docTypeLabel("20-F"), "20-F");
  assert.equal(docTypeLabel("10-K"), "Annual report");
  assert.equal(docTypeLabel("sustainability_report"), "Sustainability report");
});

test("AC-93: 1,000 ids made by Add field all differ and none is field_<number>", () => {
  const ids = Array.from({ length: 1000 }, newFieldId);
  assert.equal(new Set(ids).size, 1000);
  assert.deepEqual(ids.filter((id) => /^field_\d+$/.test(id)), []);
});

test("AC-147: step 1 reads the flow again only while the identity run is pending or running", () => {
  assert.deepEqual(
    ["pending", "running", "completed", "failed", null].map(identityPolls),
    [true, true, false, false, false],
  );
});

test("AC-148: the identity status line of an ended run with one company left reads as before", () => {
  assert.equal(
    identityStatus("run-1", "completed", 1)!.text,
    "The identity run ended (completed): 1 company still has no identifier. Add an ISIN, LEI or CIK for it, or try again.",
  );
});

test("AC-106: an Argus banner drops the leading status number, and only that", () => {
  assert.equal(plainError("400: Add companies in step 1 first."), "Add companies in step 1 first.");
  assert.equal(plainError("Failed to fetch"), "Failed to fetch");
  assert.equal(plainError("2025: a year, not a status"), "2025: a year, not a status");
});

test("AC-104, AC-105: a step in the URL is 1 to 5, or not a step; no step is step 1", () => {
  assert.deepEqual(["1", "3", "5", undefined].map(stepFromUrl), [1, 3, 5, 1]);
  assert.deepEqual(["7", "2.5", "-1", "0", "x", ""].map(stepFromUrl), [null, null, null, null, null, null]);
});

test("AC-59: companies are locked once the flow has a run or a fresh starting flag; a flag older than 60 s does not lock", () => {
  const now = Date.parse("2026-11-13T10:00:00Z");
  const flow = { run_id: null, starting: false, starting_at: null, updated_at: "2026-11-13T09:00:00Z" };
  assert.equal(companiesLocked(flow, now), false);
  assert.equal(companiesLocked({ ...flow, run_id: "r1" }, now), true);
  assert.equal(companiesLocked({ ...flow, starting: true, starting_at: "2026-11-13T09:59:55Z" }, now), true);
  assert.equal(companiesLocked({ ...flow, starting: true, starting_at: "2026-11-13T09:58:00Z" }, now), false);
  assert.equal(companiesLocked({ ...flow, starting: true, updated_at: "2026-11-13T09:59:55Z" }, now), true); // no starting_at: the last write
});

test("AC-95: the Release question names the schema, its version and the companies it then extracts", () => {
  assert.equal(releaseQuestion("S", 1, 3), "Release S v1? A released version cannot be changed or withdrawn. It then extracts all 3 companies.");
  assert.equal(releaseQuestion("S", 2, 1), "Release S v2? A released version cannot be changed or withdrawn. It then extracts 1 company.");
  assert.equal(releaseQuestion("S", 1, 0), "Release S v1? A released version cannot be changed or withdrawn."); // no kept files yet
});

test("AC-67: a draft row carries its first two company names and how many more", () => {
  const names = ["Apple", "Microsoft", ...Array.from({ length: 13 }, (_, i) => `C${i}`)];
  assert.equal(companiesSummary(names), "Apple, Microsoft +13");
  assert.equal(companiesSummary(["Apple", "Microsoft"]), "Apple, Microsoft");
  assert.equal(companiesSummary(["Apple"]), "Apple");
  const draft = { flow_id: "f1", run_id: null, step: 2, started_by: "dev", started_by_name: "Dev", created_at: "2026-11-13T09:05:00Z",
    companies: names.map((name) => ({ company_id: name, name })) } as unknown as ArgusDraft;
  const [row] = argusRows([], [], [draft]);
  assert.equal(row.label, "New extraction");
  assert.equal(row.names, "Apple, Microsoft +13");
});

test("AC-76: the line above the table names the step a pressed tile shows", () => {
  assert.equal(filterLine(3), "Showing step 3 Schema only.");
  assert.equal(filterLine(null), null);
});
