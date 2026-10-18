import test from "node:test";
import assert from "node:assert/strict";
import { cellHash, currentFact, errorDetail, historyLine, outcomeClass, ratifiedLine } from "../src/lib/barrier.ts";
import { decisionChoices } from "../src/lib/reviewKeys.ts";

test("ratifiedLine names who ratified a derived rating, or says it is hand-rated", () => {
  assert.equal(ratifiedLine({ basis: "hand_rated", ratified_by: null, last_verified: "2026-08-14" }), "hand-rated 2026-08-14");
  assert.equal(ratifiedLine({ basis: "derived", ratified_by: "a.approver", last_verified: "2026-10-20" }), "ratified by a.approver 2026-10-20");
});

test("outcomeClass maps pass, fail, unknown and mixed to their own class, anything else to unknown", () => {
  assert.equal(outcomeClass("pass"), "tb-outcome tb-outcome-pass");
  assert.equal(outcomeClass("fail"), "tb-outcome tb-outcome-fail");
  assert.equal(outcomeClass("mixed"), "tb-outcome tb-outcome-mixed");
  assert.equal(outcomeClass("unknown"), "tb-outcome tb-outcome-unknown");
  assert.equal(outcomeClass("surprise"), "tb-outcome tb-outcome-unknown");
});

test("cellHash is the cell route, with the region URL-encoded", () => {
  assert.equal(cellHash("STL-R1", "European Union"), "#/transitionBarrier/cell/STL-R1/European%20Union");
});

test("errorDetail drops the status prefix so the server's message shows verbatim", () => {
  assert.equal(errorDetail(new Error("422: A reason is required.")), "A reason is required.");
  assert.equal(errorDetail(new Error("network down")), "network down");
});

test("historyLine reads each kind of entry as one sentence", () => {
  assert.equal(historyLine({ kind: "rating", rating: "H", basis: "hand_rated" }), "Rating H (hand-rated)");
  assert.equal(historyLine({ kind: "rating", rating: "M", basis: "derived" }), "Rating M (derived)");
  assert.equal(historyLine({ kind: "fact", fact: "price", value: "30 USD/tCO2, Doc 1" }), "Fact price: 30 USD/tCO2, Doc 1");
  assert.equal(historyLine({ kind: "choice", fact: "price", value: "30 USD/tCO2, Doc 1", reason: "newer" }), "Chose price: 30 USD/tCO2, Doc 1 (newer)");
  assert.equal(historyLine({ kind: "decision", decision: "approve" }), "Decision: approve");
});

test("a barrier review item is decided with approve or reject only", () => {
  assert.deepEqual(decisionChoices("barrier_cell", "transition_barrier_derivation"), ["approve", "reject"]);
});

test("currentFact falls back to the first fact that can be entered until one is picked", () => {
  const facts = [{ id: "ratio", type: null }, { id: "price", type: "number" }, { id: "levy", type: "boolean" }];
  assert.equal(currentFact("", facts), "price");
  assert.equal(currentFact("levy", facts), "levy");
  assert.equal(currentFact("ratio", facts), "price");
  assert.equal(currentFact("", []), "");
});
