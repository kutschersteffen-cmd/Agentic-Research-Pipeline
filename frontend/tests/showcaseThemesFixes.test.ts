// Showcase fixes, R&D Lab screens (spec showcase-themes-fixes, PR 1): the wording and rules behind the pages.
import { test } from "node:test";
import assert from "node:assert/strict";
import { canAddSource, proposalFailedText } from "../src/lib/research.ts";
import { builtUniverseLine, fundSearchEmptyText } from "../src/lib/universeBuilder.ts";
import { savedDraftLine, webSourceUrl } from "../src/lib/themeBuilder.ts";
import { runGone } from "../src/lib/runs.ts";
import { FIND_COMPANIES_FIRST, companiesFound } from "../src/lib/position.ts";
import type { Dossier, ResearchRound } from "../src/types.ts";

const round = (over: Partial<ResearchRound>): ResearchRound => ({
  round: 1, taxonomy_version: 1, plan_status: "proposal_failed", proposal_run_id: null, plan_approved_by: null,
  plan_approved_at: null, sources: [], note: null, note_run_id: null, search_unreachable: false, ...over,
});

test("a failed proposal says why and leaves the plan to fill by hand", () => {  // AC-24, AC-106
  assert.equal(proposalFailedText(round({ search_unreachable: true })),
    "The web search could not be reached, so no sources were proposed. Add a source by hand below, or propose again.");
  assert.equal(proposalFailedText(round({})), "The source proposal failed. Propose again, or add a source by hand below.");
  assert.equal(canAddSource(round({})), true);
  assert.equal(canAddSource(round({ plan_status: "proposed" })), true);
  assert.equal(canAddSource(round({ plan_status: "approved" })), false);
  assert.equal(canAddSource(round({ plan_status: "proposing" })), false);
});

test("the fund list's empty text tells search down from nothing found", () => {  // AC-30, AC-31
  assert.equal(fundSearchEmptyText(null), undefined);
  assert.equal(fundSearchEmptyText({ search_unreachable: true }),
    "The web search could not be reached. Download the fund's holdings file from the provider's website and upload it in step 2 below.");
  assert.equal(fundSearchEmptyText({ search_unreachable: false }), "No candidates found. Try another name.");
});

test("a built universe is named by its file, not its server path", () => {  // AC-93
  const line = builtUniverseLine({ path: "/srv/runs/_universes/_raw_holdings_x_universe.json", company_count: 3 });
  assert.equal(line, 'Built 3 companies and saved them as the universe "_raw_holdings_x_universe.json". Pick it under "Or pick a saved universe" on the Thematic Universe page.');
  assert.ok(!line.includes("_universes"));
});

test("saved draft line", () => {  // AC-37
  assert.equal(savedDraftLine("Grid"),
    'Saved as draft "Grid". Ratify it and release its schema in the Taxonomy Library, then come back and run it.');
});

test("a citation links to its web source only for http(s) and only without a stored file", () => {  // AC-40, AC-41, AC-113
  assert.equal(webSourceUrl({ source_filename: null, source_url: "https://www.sec.gov/x.htm" }), "https://www.sec.gov/x.htm");
  assert.equal(webSourceUrl({ source_filename: null, source_url: null }), null);
  assert.equal(webSourceUrl({ source_filename: null, source_url: "javascript:alert(1)" }), null);
  assert.equal(webSourceUrl({ source_filename: "r.pdf", source_url: "https://x.org/r.pdf" }), null);
});

test("a 404 poll means the run is gone; other errors are not", () => {  // AC-45, AC-116
  assert.equal(runGone("404: Run not found"), true);
  assert.equal(runGone("500: Internal Server Error"), false);
});

test("standards wait for step 4", () => {  // AC-94, AC-117
  const steps = (state: string) => [{ number: 4, title: "Find companies", state, detail: "", href: null }] as Dossier["steps"];
  assert.equal(companiesFound(steps("waiting")), false);
  assert.equal(companiesFound(steps("open")), false);
  assert.equal(companiesFound(steps("done")), true);
  assert.equal(FIND_COMPANIES_FIRST, "Find companies first: finish step 4 of the dossier.");
});
