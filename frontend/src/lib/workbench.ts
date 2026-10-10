import type { CompanyRef, WorkbenchMapping, WorkbenchRoute, WorkbenchRow } from "../types";

export const routeText = (r: WorkbenchRoute): string =>
  r.status === "routed" ? (r.market === "esef" ? "EU (ESEF)" : "US (SEC)") : r.status === "no_source" ? "No XBRL source yet" : "Not routed";

export const mappingText = (m: WorkbenchMapping): string =>
  ({
    mapped: "Mapped",
    ambiguous: "Ambiguous",
    unmapped: "Not in the master",
    no_identifier: "No identifier",
  })[m.status];

/** The enriched companies of the ticked rows, in table order (duplicate rows stay). */
export const selectedCompanies = (rows: WorkbenchRow[], selected: Set<string>): CompanyRef[] =>
  rows.filter((r) => selected.has(r.company.company_id)).map((r) => r.company);

export const handoverName = (target: "extraction" | "xbrl"): string =>
  target === "xbrl" ? "Argus universe for XBRL facts" : "Argus universe for extraction";
