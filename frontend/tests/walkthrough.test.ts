import { test } from "node:test";
import assert from "node:assert/strict";
import { markQuotes, notRecordedNote, parseWalkthroughParams, recordWalkthroughHref, rowWalkthroughHref, steps, walkthroughHref } from "../src/lib/walkthrough.ts";
import type { Walkthrough } from "../src/types.ts";

/** What App's parseHash hands the page: the hash after the tab, split on "/", each part decoded. */
const routeParams = (href: string) => href.replace("#/argusWalkthrough/", "").split("/").map(decodeURIComponent);

const passage = (rank: number) => ({ rank, doc_id: "doc_1", doc_title: "10-K 2025", section: "MD&A", char_start: rank * 100, char_end: rank * 100 + 90, text: `passage ${rank}` });

// AC-2 shaped: high-risk field, blind verifier disagrees, adjudicator unresolved, 12 passages.
const AC2: Walkthrough = {
  run_id: "run_2", run_type: "extraction", company_id: "cat", company_name: "Caterpillar",
  item: "tc_capex_total", item_name: "Total capex", recorded: true, trace_run_id: "run_2",
  rows: [{
    field_id: "tc_capex_total", field_name: "Total capex", value: 2.794, unit: "USD billion", period_end: "2025-12-31",
    confidence: 0.4, method: "adjudicated", route: "review", route_reasons: ["verifier_disagrees"],
    citations: [{ doc_id: "doc_1", quote: "capex of 2,821", grounded: true }, { doc_id: "doc_1", quote: "2.794", grounded: false }],
    alternatives: [{ value: 2821, raw_value_text: "2,821", source: "extractor", citations: [] }],
    corrections: [{ rule: "unit_scale", attribute: "unit", original: "USD million", corrected: "USD billion", reason: "scale" }],
    checks: [{ check_id: "a", outcome: "pass" }, { check_id: "b", outcome: "fail" }],
  }],
  passages: Array.from({ length: 12 }, (_, i) => passage(i + 1)),
  extractor: { model: "claude-x", prompt_version: "p1", answer: { values: [{ value: 2821, state: "found", citations: [] }], confidence: 0.4 } },
  verifier: { model: "claude-v", prompt_version: "p2", blind: true, answer: { values: [{ value: 2.794 }], confidence: 0.7 }, verdict: { agrees: false, disagreement_type: "value", notes: "differs", confidence: 0.5 } },
  adjudicator: { model: "claude-a", prompt_version: "p3", answer: { settled: false, notes: "unclear" } },
  vision: null, skipped: null, not_recorded_reason: null,
};
const AC2_PICK = { periodEnd: "2025-12-31" };

test("href round-trips through the route params, with unspecified and a basis holding ':'", () => {
  const cases: [string, string, string, string | null | undefined, string | null | undefined][] = [
    ["run_1", "co/1", "tc_capex_total", "2025-12-31", undefined],
    ["run_1", "co 1", "tc_capex_total", null, undefined],
    ["run_1", "c", "ta_action_text", "2030-12-31", "action:3"],
    ["run_1", "c", "capex", undefined, undefined],
  ];
  for (const [runId, companyId, item, periodEnd, basis] of cases) {
    const href = walkthroughHref(runId, companyId, item, periodEnd, basis);
    assert.ok(href.startsWith("#/argusWalkthrough/"), href);
    assert.deepEqual(parseWalkthroughParams(routeParams(href)), {
      runId, companyId, item,
      periodEnd: periodEnd === undefined ? undefined : periodEnd ?? "unspecified",
      basis: basis ?? undefined,
    });
  }
  assert.equal(walkthroughHref("r", "c", "f", "2025-12-31"), "#/argusWalkthrough/r/c/f/2025-12-31");
  assert.equal(walkthroughHref("r", "c", "f", null), "#/argusWalkthrough/r/c/f/unspecified");
  assert.equal(walkthroughHref("r", "c", "f", "2030-12-31", "action:3"), "#/argusWalkthrough/r/c/f/2030-12-31?basis=action:3");
  assert.deepEqual(parseWalkthroughParams([]), { runId: undefined, companyId: undefined, item: undefined, periodEnd: undefined, basis: undefined });
});

test("a data-point walkthrough has ten steps; blind verify disagrees, adjudicator unresolved", () => {
  const s = steps(AC2, AC2_PICK);
  assert.deepEqual(s.map((x) => x.n), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  assert.deepEqual(s.map((x) => x.name), [
    "Tagged data first", "Find evidence", "Extract", "Verify, blind", "Adjudicate",
    "Ground every quote", "Combine into one record", "Auto-corrections", "Checks", "Route",
  ]);
  assert.deepEqual(s.map((x) => x.label), [
    "skipped", "12 passages", "2,821 · confidence 0.40", "disagrees", "unresolved",
    "1 of 2 grounded", "2.794 + 1 alternative", "1 correction", "1 failed", "review",
  ]);
  assert.deepEqual(s.map((x) => x.kind), ["code", "code", "llm", "llm", "llm", "code", "code", "code", "code", "code"]);
  assert.equal(s[2].model, "claude-x");
  assert.deepEqual(s[2].answer, AC2.extractor!.answer);
  assert.ok(s.every((x) => x.recorded));
});

test("a non-blind verifier is named Verify; agreement and no adjudicator read agrees / not needed", () => {
  const w: Walkthrough = { ...AC2, verifier: { model: "v", prompt_version: "p", blind: false, answer: { agrees: true, confidence: 0.9, notes: "" }, verdict: null }, adjudicator: null };
  const s = steps(w, AC2_PICK);
  assert.equal(s[3].name, "Verify");
  assert.equal(s[3].label, "agrees");
  assert.equal(s[4].label, "not needed");
});

test("not recorded: steps 2, 3 and 5 read not recorded; the verify step shows the row", () => {
  const w: Walkthrough = { ...AC2, recorded: false, passages: [], extractor: null, verifier: null, adjudicator: null, not_recorded_reason: "before_traces" };
  const s = steps(w, AC2_PICK);
  assert.equal(s.length, 10);
  for (const i of [1, 2, 4]) {
    assert.equal(s[i].label, "not recorded", s[i].name);
    assert.equal(s[i].recorded, false, s[i].name);
  }
  assert.equal(s[3].name, "Verify");
  assert.equal(s[3].recorded, true);
  assert.equal(s[9].label, "review");
});

test("skipped fields label the step that stopped them and the rest not reached", () => {
  const skip = (skipped: Walkthrough["skipped"]) =>
    steps({ ...AC2, passages: [], extractor: null, verifier: null, adjudicator: null, skipped }, AC2_PICK).slice(0, 5).map((x) => x.label);
  assert.deepEqual(skip("tagged"), ["taken from XBRL tag", "not reached", "not reached", "not reached", "not reached"]);
  assert.deepEqual(skip("no_evidence"), ["skipped", "no passage matched", "not reached", "not reached", "not reached"]);
  assert.deepEqual(skip("derived"), ["derived by rule", "not reached", "not reached", "not reached", "not reached"]);
  assert.deepEqual(skip("documents_held"), ["skipped", "documents held", "not reached", "not reached", "not reached"]);
  assert.deepEqual(skip("not_applicable"), ["not applicable by rule", "not reached", "not reached", "not reached", "not reached"]);
});

const section = (run_type: string, item: string, rows: Record<string, unknown>[]): Walkthrough => ({
  ...AC2, run_type, item, item_name: item, rows, passages: [passage(1)],
  extractor: { model: "m", prompt_version: "p", answer: { confidence: 0.8 } },
  verifier: { model: "v", prompt_version: "p", answer: { capex_agree: true, capex_notes: "ok", disclosures_agree: false, confidence: 0.8 } },
  adjudicator: null,
});

test("Financials: six steps, none Adjudicate; XBRL overlay reads the raw value text", () => {
  const capex = { total: { value: 10, raw_value_text: "10 (from SEC XBRL tag)", citations: [{ quote: "q", grounded: true }], grounded: true }, categories: [], description_citations: [], confidence: 0.8, verifier_notes: "fine" };
  const s = steps(section("financials", "capex", [capex]));
  assert.deepEqual(s.map((x) => x.name), ["Find evidence", "Extract", "Verify", "Ground every quote", "XBRL overlay", "Combine"]);
  assert.equal(s[4].label, "XBRL value used");
  assert.equal(s[2].label, "agrees");
  assert.equal(s[3].label, "1 of 1 grounded");
  const plain = steps(section("financials", "capex", [{ ...capex, total: { ...capex.total, raw_value_text: "10" } }]));
  assert.equal(plain[4].label, "not used");
  const quoted = steps(section("financials", "capex", [{ ...capex, total: { ...capex.total, raw_value_text: "10", citations: [{ quote: "per sec xbrl", grounded: true }] } }]));
  assert.equal(quoted[4].label, "XBRL value used");
});

test("Financials with no evidence: 0 passages and model steps not reached", () => {
  const s = steps({ ...section("financials", "capex", []), passages: [], extractor: null, verifier: null });
  assert.equal(s[0].label, "0 passages");
  assert.equal(s[1].label, "not reached");
  assert.equal(s[2].label, "not reached");
});

test("TNFD: five steps, none Adjudicate; not recorded marks steps 1 and 2", () => {
  const w = section("tnfd", "disclosures", [{ confidence: 0.6, citations: [], verifier_notes: "n" }]);
  const s = steps(w);
  assert.deepEqual(s.map((x) => x.name), ["Find evidence", "Extract", "Verify", "Ground every quote", "Combine"]);
  assert.equal(s[2].label, "disagrees");
  const old = steps({ ...w, recorded: false, passages: [], extractor: null, verifier: null, not_recorded_reason: "before_traces" });
  assert.deepEqual(old.map((x) => x.label).slice(0, 2), ["not recorded", "not recorded"]);
  assert.equal(old[2].recorded, true);
});

test("plan list rows: six steps from the plan trace and the row", () => {
  const w: Walkthrough = { ...AC2, item: "ta_action_text", verifier: null, adjudicator: null, rows: [{ ...AC2.rows[0], period_end: "2030-12-31", basis: "action:3" }] };
  const s = steps(w, { periodEnd: "2030-12-31", basis: "action:3" });
  assert.deepEqual(s.map((x) => x.name), ["Find evidence", "Extract plan", "Ground every quote", "Auto-corrections", "Checks", "Route"]);
  const old = steps({ ...w, recorded: false, passages: [], extractor: null }, { periodEnd: "2030-12-31", basis: "action:3" });
  assert.deepEqual(old.map((x) => x.label).slice(0, 2), ["not recorded", "not recorded"]);
});

test("the three not-recorded notes, verbatim", () => {
  assert.equal(notRecordedNote("before_traces", 3650), "This run is from before walkthroughs were recorded. Passages and model answers were not saved; the steps below show what the stored row holds.");
  assert.equal(notRecordedNote("expired", 3650), "This run's walkthrough has expired: runs older than 3650 days keep only their results. The steps below show what the stored row holds.");
  assert.equal(notRecordedNote("write_failed", 3650), "The walkthrough for this company could not be saved during the run. The steps below show what the stored row holds.");
  assert.equal(notRecordedNote("", 3650), null);
});

test("quoted words are marked inside passage text", () => {
  assert.deepEqual(markQuotes("Total capex of 2,821 in 2025", ["capex of 2,821", "missing"]), [
    { text: "Total ", mark: false }, { text: "capex of 2,821", mark: true }, { text: " in 2025", mark: false },
  ]);
  assert.deepEqual(markQuotes("abc", []), [{ text: "abc", mark: false }]);
});

const PLAN = "sch_transition_plan_actions";

test("row links: the field's period, unspecified without one, basis only on a plan list row (AC-50, AC-52, AC-61)", () => {
  const f = (field_id: string, period_end: string | null, basis: string | null = null) => ({ field_id, period_end, basis });
  assert.equal(rowWalkthroughHref("r", { company_id: "cat" }, f("tc_capex_total", "2025-12-31")), "#/argusWalkthrough/r/cat/tc_capex_total/2025-12-31");
  assert.equal(rowWalkthroughHref("r", { company_id: "cat" }, f("tc_capex_total", null)), "#/argusWalkthrough/r/cat/tc_capex_total/unspecified");
  // another schema's basis is part of the value, not the route
  assert.equal(rowWalkthroughHref("r", { company_id: "cat", schema_id: "sch_x" }, f("tc_capex_total", "2025-12-31", "consolidated")), "#/argusWalkthrough/r/cat/tc_capex_total/2025-12-31");
  const plan = { company_id: "cat", schema_id: PLAN };
  assert.equal(rowWalkthroughHref("r", plan, f("ta_action_text", "2030-12-31", "action:3")), "#/argusWalkthrough/r/cat/ta_action_text/2030-12-31?basis=action:3");
  assert.equal(rowWalkthroughHref("r", plan, f("ta_operates_eu", "2025-12-31", "action:3")), "#/argusWalkthrough/r/cat/ta_operates_eu/2025-12-31");
  // a review item knows no schema: only a list basis (`action:`, `region:`, `target:`, `phaseout:`) marks a plan row
  assert.equal(rowWalkthroughHref("r", { company_id: "cat" }, f("ta_target_pct", null, "target:1")), "#/argusWalkthrough/r/cat/ta_target_pct/unspecified?basis=target:1");
});

test("record links: a section route with no period (AC-53, AC-59, AC-60)", () => {
  assert.equal(recordWalkthroughHref("r", "cat", "capex"), "#/argusWalkthrough/r/cat/capex");
  assert.equal(recordWalkthroughHref("r", "cat", "disclosures"), "#/argusWalkthrough/r/cat/disclosures");
});

test("an empty quote marks nothing", () => {
  assert.deepEqual(markQuotes("abc", [""]), [{ text: "abc", mark: false }]);
});
