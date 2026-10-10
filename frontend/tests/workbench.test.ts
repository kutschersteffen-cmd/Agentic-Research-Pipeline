import test from "node:test";
import assert from "node:assert/strict";
import { handoverCompanies, handoverName, mappingText, routeText, selectedCompanies } from "../src/lib/workbench.ts";
import type { WorkbenchMapping, WorkbenchRoute, WorkbenchRow } from "../src/types.ts";

const route = (market: "sec" | "esef" | null, status: WorkbenchRoute["status"]): WorkbenchRoute => ({
  market, status, basis: "", detail: "",
});

test("routeText", () => {
  assert.equal(routeText(route("sec", "routed")), "US (SEC)");
  assert.equal(routeText(route("esef", "routed")), "EU (ESEF)");
  assert.equal(routeText(route(null, "no_source")), "No XBRL source yet");
  assert.equal(routeText(route(null, "unrouted")), "Not routed");
});

test("mappingText has a distinct text per status", () => {
  const statuses: WorkbenchMapping["status"][] = ["mapped", "ambiguous", "unmapped", "no_identifier"];
  const texts = statuses.map((status) =>
    mappingText({ status, issuer_key: null, key_scheme: null, identifiers: {}, candidates: [] }));
  assert.equal(new Set(texts).size, 4);
  assert.ok(texts.every((t) => t !== ""));
});

test("selectedCompanies keeps table order, duplicates and the enriched company", () => {
  const row = (id: string, cik?: string) => ({ company: { company_id: id, name: id, cik } }) as WorkbenchRow;
  const rows = [row("a"), row("b", "123"), row("a"), row("c")];
  const out = selectedCompanies(rows, new Set(["c", "a", "b"]));
  assert.deepEqual(out.map((c) => c.company_id), ["a", "b", "a", "c"]);
  assert.equal(out[1].cik, "123");
  assert.deepEqual(selectedCompanies(rows, new Set(["b"])).map((c) => c.company_id), ["b"]);
  assert.deepEqual(selectedCompanies(rows, new Set()), []);
});

test("handoverCompanies saves the enriched rows for the whole universe too", () => {
  const row = (id: string, cik?: string) => ({ company: { company_id: id, name: id, cik } }) as WorkbenchRow;
  const rows = [row("a", "1"), row("b", "2")];
  assert.deepEqual(handoverCompanies(rows, "all", new Set()).map((c) => c.cik), ["1", "2"]);
  assert.deepEqual(handoverCompanies(rows, "selected", new Set(["b"])).map((c) => c.cik), ["2"]);
});

test("handoverName", () => {
  assert.notEqual(handoverName("extraction"), handoverName("xbrl"));
  assert.match(handoverName("xbrl"), /XBRL/);
});
