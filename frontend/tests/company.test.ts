import test from "node:test";
import assert from "node:assert/strict";
import { companyHref, encodeRef, factsUrl, primaryCitation, sourceLabel } from "../src/pages/company/companyQuery.ts";
import type { FactTrail, FactVersion } from "../src/types.ts";

test("encodeRef URL-encodes the scheme colon", () => {
  assert.equal(encodeRef("LEI:7LTWFZYICNSX8D621K86"), "LEI%3A7LTWFZYICNSX8D621K86");
  assert.equal(encodeRef("0b6d3c1e-0000-4000-8000-000000000000"), "0b6d3c1e-0000-4000-8000-000000000000");
});

test("factsUrl omits empty filters", () => {
  assert.equal(factsUrl("UNIVERSE:SIE", {}), "/api/companies/UNIVERSE%3ASIE/facts");
  assert.equal(factsUrl("UNIVERSE:SIE", { asOf: "", kind: "", fieldId: "", periodEnd: "" }), "/api/companies/UNIVERSE%3ASIE/facts");
});

test("factsUrl sends as_of as the end of the chosen local day, then the filters", () => {
  assert.equal(
    factsUrl("LEI:7LTW", { asOf: "2026-09-30", kind: "provider", fieldId: "scope1", periodEnd: "2024-12-31" }),
    `/api/companies/LEI%3A7LTW/facts?as_of=${encodeURIComponent(new Date(2026, 8, 30, 23, 59, 59, 999).toISOString())}&kind=provider&field_id=scope1&period_end=2024-12-31`,
  );
  assert.equal(factsUrl("X:1", { fieldId: "scope 1" }), "/api/companies/X%3A1/facts?field_id=scope+1");
});

const version = (over: Partial<FactVersion>): FactVersion => ({
  fact_id: 1,
  status: "approved",
  value: 1,
  valid_from: "2026-01-01T00:00:00Z",
  valid_to: null,
  superseded_by: null,
  observation: { id: 1, source_kind: "extraction", run_id: "run-1", value: 1, value_state: "found", unit: null, confidence: null, route: null, created_at: "2026-01-01T00:00:00Z" },
  citations: [],
  load: null,
  decisions: [],
  ...over,
});
const cite = (title: string, page: number | null, role: "primary" | "corroborating" = "primary") => ({
  doc_id: title, title, page, quote: null, char_start: null, char_end: null, passage_id: null, role, grounded: true,
  company_id: "acme", doc_type: "annual_report", source_filename: null, source_url: null,
});

test("sourceLabel names the primary cited document and page", () => {
  assert.equal(sourceLabel(version({ citations: [cite("Other", 3, "corroborating"), cite("Annual Report 2024", 12)] })), "Annual Report 2024 p.12");
  assert.equal(sourceLabel(version({ citations: [cite("Annual Report 2024", null)] })), "Annual Report 2024");
});

test("sourceLabel names a provider by its load date", () => {
  assert.equal(
    sourceLabel(version({ load: { source_name: "MSCI ESG", fetched_at: "2026-09-30T08:15:00Z", payload_uri: null } })),
    "MSCI ESG · 2026-09-30",
  );
});

test("sourceLabel falls back to the run", () => {
  assert.equal(sourceLabel(version({})), "run-1");
});

test("companyHref links a universe company to its page", () => {
  assert.equal(companyHref("SIE"), "#/companies/UNIVERSE%3ASIE");
  assert.equal(companyHref("A/B"), "#/companies/UNIVERSE%3AA%2FB");
});

const trail = (versions: FactVersion[]): FactTrail => ({ fact_id: 2, company_id: "acme", field_id: "f", period_end: null, basis: "", versions });

test("primaryCitation is the current version's primary citation", () => {
  const old = version({ fact_id: 1, valid_to: "2026-02-01T00:00:00Z", citations: [cite("Old report", 3)] });
  const current = version({ fact_id: 2, citations: [cite("Other", 9, "corroborating"), cite("Annual Report 2025", 45)] });
  assert.deepEqual(primaryCitation(trail([old, current])), cite("Annual Report 2025", 45));
});

test("primaryCitation is null when the current version has no primary", () => {
  const old = version({ fact_id: 1, valid_to: "2026-02-01T00:00:00Z", citations: [cite("Old report", 3)] });
  const current = version({ fact_id: 2, citations: [cite("Other", 9, "corroborating")] });
  assert.equal(primaryCitation(trail([old, current])), null);
});
