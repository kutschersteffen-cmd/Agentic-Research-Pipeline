// Showcase fixes, R&D Lab screens (spec showcase-themes-fixes, PR 2): what the pages label and link.
import { test } from "node:test";
import assert from "node:assert/strict";
import { NO_MODEL_CALLS, progressUnit, spentNothing } from "../src/lib/runs.ts";
import { intervalError, NO_COMPANIES, NOVELTY_HELP, SCANNING, scanActive } from "../src/lib/emergingThemes.ts";
import { stepLinkText } from "../src/lib/dossiers.ts";
import { reviewHref, type PlanCall } from "../src/lib/plans.ts";
import { DEMO_BANNER, exceptionText, indexErrorText, ruleTitle, SOLVER_MISSING } from "../src/lib/indexBuilder.ts";
import { alreadyRunLine, createdLabel, ic, SAMPLE_PRICES, SAMPLE_RECIPE, shortId } from "../src/lib/signals.ts";
import { companies } from "../src/lib/themeBuilder.ts";
import { citedLabel } from "../src/lib/position.ts";

test("an emerging-themes scan counts mentions, other runs companies", () => {  // AC-50, AC-98
  assert.equal(progressUnit("emerging_themes"), "mentions");
  assert.equal(progressUnit("theme"), "companies");
});

test("a finished run without tokens says so instead of $0.00", () => {  // AC-81
  assert.equal(spentNothing({ status: "completed", input_tokens: 0, output_tokens: 0 }), true);
  assert.equal(spentNothing({ status: "running", input_tokens: 0, output_tokens: 0 }), false);
  assert.equal(spentNothing({ status: "completed", input_tokens: 1, output_tokens: 0 }), false);
  assert.equal(NO_MODEL_CALLS, "No new model calls (answers reused or nothing to read)");
});

test("Emerging Themes wording", () => {  // AC-53, AC-55, AC-56
  assert.equal(SCANNING, "Scanning… candidates appear when the scan finishes.");
  assert.equal(NOVELTY_HELP, "How different this cluster is from themes in earlier scans. 100% on a first scan.");
  assert.equal(NO_COMPANIES, "None in your universe");
  assert.deepEqual(["running", "pending", "completed", undefined].map(scanActive), [true, true, false, false]);
});

test("the schedule refuses an interval below 1 hour before sending", () => {  // AC-58
  for (const h of [0, 0.5, -1, NaN]) assert.equal(intervalError(h), "Enter an interval of at least 1 hour.");
  assert.equal(intervalError(1), null);
  assert.equal(intervalError(24), null);
});

test("step 4 waiting on review links to the review", () => {  // AC-61
  assert.equal(stepLinkText(4, "#/review/theme/r1"), "Review the open items");
  assert.equal(stepLinkText(4, "#/theme/r1"), "Open the run");
});

const call = (over: Partial<PlanCall>): PlanCall => ({
  seq: 1, kind: "extraction", params: {}, status: "awaiting_review", run_id: "r", result_ref: null, ...over,
});

test("a step waiting for review links to where it is reviewed", () => {  // AC-62, AC-63, AC-64, AC-128
  assert.equal(reviewHref(call({ run_id: "r_1" })), "#/review/extraction/r_1");
  assert.equal(reviewHref(call({ kind: "universe_build" })), "#/review/theme/r");
  assert.equal(reviewHref(call({ kind: "document_discovery" })), "#/review/discovery/r");
  assert.equal(reviewHref(call({ kind: "financials_extraction" })), "#/review/financials/r");
  assert.equal(reviewHref(call({ kind: "report_render", run_id: null, result_ref: "report:7" })), "#/reporting");
  assert.equal(reviewHref(call({ kind: "xbrl_facts" })), null);
});

const METHODS = [
  { name: "least_squares", label: "Least-squares projection" },
  { name: "min_tracking_error", label: "Minimum tracking error" },
];
const fallback = (m: string) =>
  `solver.method='${m}' but cvxpy is not installed; fell back to the deterministic waterfall (pip install -e ".[optimize]")`;

test("the cvxpy fallback reads in plain words, other exceptions as they are", () => {  // AC-66, AC-67, AC-68
  assert.equal(exceptionText(fallback("least_squares"), METHODS),
    'The optimiser is not installed on this server, so this review used step-by-step capping instead of "Least-squares projection". Ask your administrator.');
  assert.equal(exceptionText(fallback("min_tracking_error"), METHODS),
    'The optimiser is not installed on this server, so this review used step-by-step capping instead of "Minimum tracking error". Ask your administrator.');
  assert.equal(exceptionText(fallback("max_score"), METHODS),
    'The optimiser is not installed on this server, so this review used step-by-step capping instead of "max_score". Ask your administrator.');
  assert.equal(exceptionText("anything else", METHODS), "anything else");
});

test("Index Construction banner and solver notice", () => {  // AC-65, AC-69
  assert.equal(DEMO_BANNER,
    "Demo data: reviews on this page run on a built-in synthetic universe of 60 companies. The results describe nothing real.");
  assert.equal(SOLVER_MISSING,
    "The optimiser is not installed on this server. A calibration that asks for it falls back to step-by-step capping, and the review says so. Ask your administrator.");
  assert.ok(!SOLVER_MISSING.includes("pip install"));
});

const CATALOGUE = {
  screens: [{ type: "metric_threshold", label: "Metric threshold" }],
  tilts: [{ type: "metric_tilt", label: "Metric tilt" }],
};

test("rule cards and errors use the catalogue's labels", () => {  // AC-70, AC-71, AC-124, AC-125
  assert.equal(ruleTitle("metric_threshold", CATALOGUE.screens), "Metric threshold");
  assert.equal(ruleTitle("metric_tilt", CATALOGUE.tilts), "Metric tilt");
  assert.equal(ruleTitle("x_tilt", CATALOGUE.tilts), "x_tilt");
  assert.equal(
    indexErrorText("422: spec › screens › 0 › metric_threshold: metric_threshold needs at least one of min_value / max_value", CATALOGUE),
    "Screen 1 (Metric threshold): needs at least one of min_value / max_value");
  assert.equal(indexErrorText("422: spec › tilts › 2 › x_tilt: bad; spec › screens › 1 › metric_threshold: worse", CATALOGUE),
    "Tilt 3 (x_tilt): bad; Screen 2 (Metric threshold): worse");
  assert.equal(indexErrorText("500: boom", null), "boom");
});

test("Signals evidence, experiments and samples", () => {  // AC-72, AC-73, AC-74, AC-123
  assert.deepEqual([ic(0.0423456), ic(2.34567), ic(null)], ["0.042", "2.346", "—"]);
  const local = new Date(2026, 10, 11, 9, 5).toISOString();
  assert.equal(createdLabel(local), "2026-11-11 09:05");
  assert.equal(shortId("aaaaaaaa1111"), "aaaaaaaa");
  assert.equal(alreadyRunLine("aaaaaaaa1111"),
    "This recipe was already run on this data. Showing the existing result (aaaaaaaa1111).");
  assert.deepEqual([SAMPLE_RECIPE, SAMPLE_PRICES], ["samples/signals-recipe.json", "samples/signals-prices.csv"]);
});

test("one company is singular", () => {  // AC-80, AC-99, AC-126
  assert.deepEqual([companies(1), companies(2)], ["1 company", "2 companies"]);
});

test("a cited item shows its title, its id only without one", () => {  // AC-87, AC-127
  assert.equal(citedLabel("itm_0d2b55df5684", { itm_0d2b55df5684: "IEA hydrogen review" }), "IEA hydrogen review");
  assert.equal(citedLabel("itm_aaaaaaaaaaaa", {}), "itm_aaaaaaaaaaaa");
});
