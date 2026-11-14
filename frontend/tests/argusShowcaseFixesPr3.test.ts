import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { keptRuns, periodText, resultRows } from "../src/lib/argusFlow.ts";
import { noteSentence, notesInWords, reasonSentence, reasonSentences, routedSentences } from "../src/lib/routeReasons.ts";
import { steps, verifyNote } from "../src/lib/walkthrough.ts";
import { companyHref } from "../src/pages/company/companyQuery.ts";
import type { ExtractedField, ExtractionRecord, Walkthrough } from "../src/types.ts";

// showcase-argus-fixes, PR 3: steps 4 and 5, walkthrough, company link.

test("AC-114: the four reasons of a draft schema's value read as sentences", () => {
  assert.deepEqual(["unreleased_version", "check_failed", "first_audit_pending", "below_auto_accept_min"].map(reasonSentence), [
    "The schema is a draft, so every value is reviewed.",
    "A check on this value failed.",
    "The first values of a new schema version are always reviewed.",
    "Confidence is below the level for automatic acceptance.",
  ]);
});

/** A backend file, found from any parent folder (the mutation check runs these tests from a copy under frontend/.stryker-tmp). */
function backendFile(path: string): string {
  for (let up = "../../"; up.length < 40; up += "../") {
    const url = new URL(`${up}backend/${path}`, import.meta.url);
    if (existsSync(url)) return readFileSync(url, "utf8");
  }
  throw new Error(`backend/${path} not found`);
}

test("AC-115: every ReasonCode and every reason literal in routing.py has a sentence", () => {
  const review = backendFile("arp/schemas/review.py");
  const routing = backendFile("arp/extraction/routing.py");
  const enumBody = /class ReasonCode\(StrEnum\):([\s\S]*?)\n\n/.exec(review)![1];
  const codes = [
    ...[...enumBody.matchAll(/= "([a-z_]+)"/g)].map((m) => m[1]),
    ...[...routing.matchAll(/"([a-z]+(?:_[a-z]+)+)"/g)].map((m) => m[1]),
  ];
  assert.ok(codes.length >= 20, `found ${codes.length} codes`);
  for (const code of new Set(codes)) {
    const text = reasonSentence(code);
    assert.ok(text.endsWith(".") && !text.includes("_") && !text.startsWith("Reason:"), `${code}: ${text}`);
  }
});

test("AC-156: a code with no sentence reads `Reason: <code with spaces>.`", () => {
  assert.equal(reasonSentence("some_new_code"), "Reason: some new code.");
});

test("AC-116: the unit converter's note reads as a sentence; other notes stay", () => {
  assert.equal(noteSentence("cannot convert 'short tons' to 'tCO2e' (unknown_unit)"), 'The unit "short tons" could not be converted to tCO2e.');
  assert.equal(noteSentence("The value is outside the field's allowed range."), "The value is outside the field's allowed range.");
});

const field = (id: string, f: Partial<ExtractedField> = {}): ExtractedField =>
  ({ field_id: id, field_name: id, value: 1, citations: [], confidence: 0.9, grounded: true, conflicting_sources: false,
     value_state: "found", period_end: "2025-12-31", ...f });
const record = (cid: string, fields: ExtractedField[], runId = "run_new"): ExtractionRecord =>
  ({ company_id: cid, issuer_key: `k${cid}`, name: cid, schema_id: "s", run_id: runId, fields, overall_confidence: 0.9, needs_review: false } as ExtractionRecord);

test("AC-121: a Period per row, a field's newer period first; other fields keep their order", () => {
  const rows = resultRows([record("a", [field("rev", { period_end: "2025-06-30" }), field("capex"), field("rev", { period_end: "2026-06-30" })])], []);
  assert.deepEqual(rows.map((r) => [r.field, r.period]), [["rev", "2026-06-30"], ["rev", "2025-06-30"], ["capex", "2025-12-31"]]);
});

test("AC-122: a value with no period end reads —", () => {
  assert.equal(periodText(null), "—");
  assert.equal(periodText(undefined), "—");
  assert.equal(periodText("2026-06-30"), "2026-06-30");
});

test("AC-113, AC-150: every value row links the walkthrough of the run that extracted it", () => {
  const [row] = resultRows([record("msft", [field("capex")], "run_2026_11_10")], []);
  assert.equal(row.walkthrough, "#/argusWalkthrough/run_2026_11_10/msft/capex/2025-12-31");
  const stop = { item_key: "d", kind: "other", run_id: "r", run_type: "extraction", payload: { company_id: "d" }, state: "pending",
    escalated: false, high_risk: false, decision: null } as never;
  assert.equal(resultRows([], [stop])[0].walkthrough, undefined); // a company-level row has no value to walk through
});

test("AC-118: only a skipped company with an earlier run is kept from it", () => {
  const companies = [{ company_id: "aapl" }, { company_id: "msft" }, { company_id: "sap" }];
  const rows = [{ company_id: "msft", run_id: "run_old", date: "2026-11-10" }, { company_id: "sap", run_id: "run_sap", date: "2026-11-09" }];
  assert.deepEqual(keptRuns(companies, { msft: "skip", sap: "run" }, rows), [{ company_id: "msft", run_id: "run_old", date: "2026-11-10" }]);
});

test("AC-126: a blind re-extraction that failed shows the verdict's note", () => {
  const w = {
    run_id: "r", run_type: "extraction", company_id: "c", company_name: "C", item: "f", item_name: "F", recorded: true, trace_run_id: "r",
    rows: [{ field_id: "f", period_end: "2025-12-31", route: "review", route_reasons: [], citations: [] }], passages: [],
    extractor: { model: "m", prompt_version: "p", answer: { values: [] } },
    verifier: { model: "v", prompt_version: "p", blind: true, answer: null,
      verdict: { agrees: false, notes: "Blind re-extraction failed: the answer did not fit the field type." } },
    adjudicator: null, vision: null, skipped: null, not_recorded_reason: null,
  } as unknown as Walkthrough;
  const blind = steps(w, { periodEnd: "2025-12-31" }).find((s) => s.name === "Verify, blind")!;
  assert.ok(verifyNote(blind, w)!.includes("Blind re-extraction failed: the answer did not fit the field type."));
  assert.equal(verifyNote({ answer: { agrees: true } }, w), null); // an answer is shown in its tabs instead
});

test("AC-128: a company with no central id links its universe id, as on main; with one, that record", () => {
  assert.equal(companyHref("AAPL"), "#/companies/UNIVERSE%3AAAPL");
  assert.equal(companyHref("AAPL", null), "#/companies/UNIVERSE%3AAAPL");
  assert.equal(companyHref("AAPL", "3f2b8c1e-5d47-4a9b-8c21-0a1b2c3d4e5f"), "#/companies/3f2b8c1e-5d47-4a9b-8c21-0a1b2c3d4e5f");
});

// Mutation check: what the functions above must not lose.

test("kept runs: the earlier run is the skipped company's own, wherever it is listed", () => {
  const rows = [{ company_id: "sap", run_id: "run_sap", date: "2026-11-09" }, { company_id: "msft", run_id: "run_old", date: "2026-11-10" }];
  assert.deepEqual(keptRuns([{ company_id: "msft" }], { msft: "skip" }, rows), [{ company_id: "msft", run_id: "run_old", date: "2026-11-10" }]);
  assert.deepEqual(keptRuns([{ company_id: "msft" }], { msft: "skip" }, []), []); // no earlier run: nothing kept
});

test("periods: a field's dated rows come before its undated one", () => {
  const rows = resultRows([record("a", [field("rev", { period_end: null }), field("rev", { period_end: "2025-06-30" }), field("rev", { period_end: "2026-06-30" })])], []);
  assert.deepEqual(rows.map((r) => r.period), ["2026-06-30", "2025-06-30", null]);
  const back = resultRows([record("a", [field("rev", { period_end: "2025-06-30" }), field("rev", { period_end: null })])], []);
  assert.deepEqual(back.map((r) => r.period), ["2025-06-30", null]);
});

test("result rows: the grounded citation first, else the first, else none", () => {
  const c = (quote: string, grounded: boolean) => ({ doc_id: "d", doc_type: "10-K", quote, grounded }) as never;
  const cite = (citations: never[]) => resultRows([record("a", [field("f", { citations })])], [])[0].citation;
  assert.equal((cite([c("one", false), c("two", true)]) as { quote: string }).quote, "two");
  assert.equal((cite([c("one", false)]) as { quote: string }).quote, "one");
  assert.equal(cite([]), null);
});

test("a company-level row without details reads Whole company / Stopped for review under its item key", () => {
  const item = { item_key: "zeta", kind: "other", run_id: "r", run_type: "extraction", payload: {}, state: "pending",
    escalated: false, high_risk: false, decision: null } as never;
  const [row] = resultRows([], [item]);
  assert.deepEqual([row.companyId, row.company, row.field, row.value, row.notFound, row.period], ["zeta", "zeta", "Whole company", "Stopped for review", false, null]);
});

test("the unit note is rewritten only when it is the whole note", () => {
  for (const note of ["note: cannot convert 'a' to 'b' (unknown_unit)", "cannot convert 'a' to 'b' (unknown_unit); see above"]) {
    assert.equal(noteSentence(note), note);
  }
});

test("a verify step's note: only a non-empty text, and none without a verifier", () => {
  const w = (verifier: unknown) => ({ recorded: true, verifier }) as never;
  const none = { answer: null };
  assert.equal(verifyNote(none, w(null)), null);
  assert.equal(verifyNote(none, w({ verdict: { notes: "" } })), null);
  assert.equal(verifyNote(none, w({ verdict: { notes: 5 } })), null);
  assert.equal(verifyNote(none, w({ verdict: {} })), null);
  assert.equal(verifyNote(none, { recorded: false, verifier: { verdict: { notes: "x" } } } as never), null); // not recorded: the stored row speaks
});

test("AC-114, AC-156 in the review detail: Routed for review, then one sentence per reason, checks left out", () => {
  assert.equal(routedSentences(["unreleased_version", "check_failed", "check:consistency.entity"]),
    "Routed for review: The schema is a draft, so every value is reviewed. A check on this value failed.");
  assert.equal(routedSentences(["some_new_code"]), "Routed for review: Reason: some new code.");
  assert.equal(routedSentences(["check:consistency.entity"]), null);
  assert.equal(routedSentences([]), null);
});

test("AC-116 where the note is shown: a unit note inside a run's verifier notes reads as a sentence", () => {
  assert.equal(notesInWords("No grounded citation supports this value. cannot convert 'short tons' to 'tCO2e' (unknown_unit)"),
    'No grounded citation supports this value. The unit "short tons" could not be converted to tCO2e.');
  assert.equal(notesInWords("cannot convert 'a' to 'b' (x) cannot convert 'c' to 'd' (y)"),
    'The unit "a" could not be converted to b. The unit "c" could not be converted to d.');
  assert.equal(notesInWords("The verifier agrees."), "The verifier agrees.");
});

test("the walkthrough's Route reads the reasons as sentences, its failed checks left out", () => {
  assert.equal(reasonSentences(["verifier_disagrees", "check:numeric.in_span", "low_confidence"]),
    "The verifier disagrees with the extracted value. Confidence is low.");
  assert.equal(reasonSentences(["check:numeric.in_span"]), "");
});
