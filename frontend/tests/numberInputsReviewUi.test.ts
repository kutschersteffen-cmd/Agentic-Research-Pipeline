import test from "node:test";
import assert from "node:assert/strict";
import { listText, multipliersText, parseList, parseMultipliers, parseNumberList } from "../src/lib/draftInput.ts";
import { specProblem } from "../src/lib/indexSpecCheck.ts";
import { excerptView } from "../src/lib/sourceText.ts";
import { earlierFailedLine, flowReviewHref, readEach } from "../src/lib/argusFlow.ts";
import { waiting } from "../src/lib/argusStart.ts";
import { refineDoc, rfpId } from "../src/lib/agent.ts";

test("parseList and listText", () => {
  assert.deepEqual(parseList(" a , b ,, c ,"), ["a", "b", "c"]);
  assert.equal(listText(["a", "b"]), "a, b");
  assert.equal(listText([]), "");
});

test("parseNumberList keeps finite numbers only", () => {
  assert.deepEqual(parseNumberList("0.5, -1, 2"), [0.5, -1, 2]);
  assert.deepEqual(parseNumberList("2., -, 1e, x, , -0.25"), [2, -0.25]);
});

test("parseMultipliers and multipliersText", () => {
  assert.deepEqual(parseMultipliers("Energy = 1.5\nUtilities=0.5"), { Energy: 1.5, Utilities: 0.5 });
  assert.deepEqual(parseMultipliers("Energy\nUtilities = \nTech = 0\nBank = -1\n = 2\nOil = x\nGas = 1.2"), { Gas: 1.2 });
  assert.deepEqual(Object.entries(parseMultipliers("Oil = 1\nGas = 2\nOil = 3")), [["Oil", 3], ["Gas", 2]]);
  assert.equal(multipliersText({ Energy: 1.5, Oil: 2 }), "Energy = 1.5\nOil = 2");
});

const wf = { solver: { method: "waterfall" } };
test("specProblem", () => {
  const W = "Choose the field to weight by under 3 · Base weighting.";
  assert.equal(specProblem({ base_weighting: { scheme: "metric" }, tilts: [], constraints: wf }), W);
  assert.equal(specProblem({ base_weighting: { scheme: "inverse_metric", field: "" }, tilts: [], constraints: wf }), W);
  assert.equal(specProblem({ base_weighting: { scheme: "equal" }, constraints: wf,
    tilts: [{ type: "bucket_tilt" }, { type: "metric_tilt", normalisation: "group_max", group_by: "none" }] }), "Choose the group of tilt 2 under 4 · Tilts.");
  assert.equal(specProblem({ base_weighting: { scheme: "equal" }, constraints: wf,
    tilts: [{ type: "metric_tilt", normalisation: "group_max", group_by: "" }] }), "Choose the group of tilt 1 under 4 · Tilts.");
  assert.equal(specProblem({ base_weighting: { scheme: "metric", field: "esg_score" }, constraints: wf,
    tilts: [{ type: "metric_tilt", normalisation: "group_max", group_by: "sector" }] }), null);
  assert.equal(specProblem({ base_weighting: { scheme: "metric" }, tilts: [], constraints: { solver: { method: "max_score" } } }), W);
  assert.equal(specProblem({ base_weighting: { scheme: "equal" }, tilts: [], constraints: { solver: { method: "max_score" } } }),
    "Choose the field to maximise under 5 · Constraints before running a max_score methodology.");
});

const T = "Intro here. In 2025 revenue grew to €39bn, up 16%. Backlog hit €136bn. Outro.";
const s = T.indexOf("revenue grew to €39bn");
const e = s + "revenue grew to €39bn".length;
const TX = (o: object) => ({ run_id: "r", item_key: "k", doc_id: "d", doc_type: "pdf", page: 2, page_start: 1000, page_text: T, ...o }) as never;

test("excerptView reads page offsets and names the page once", () => {
  const v = excerptView({ title: "AR 2025", src: "", text: TX({ char_start: 1000 + s, char_end: 1000 + e }) }) as { caption: string; parts: object };
  assert.deepEqual(v.parts, { lead: "Intro here.", before: "In 2025 ", mark: "revenue grew to €39bn", after: ", up 16%.", trail: "Backlog hit €136bn." });
  assert.equal(v.caption, "AR 2025 · p. 2");
  assert.deepEqual(excerptView({ title: "AR 2025", src: "", quote: "Q", text: TX({ char_start: 1000, char_end: 1000 + T.length + 1 }) }), { caption: "AR 2025 · p. 2", quote: "Q" });
  assert.equal(excerptView({ title: "AR 2025 — p. 2", src: "", text: TX({ char_start: 1000 + s, char_end: 1000 + e }) })?.caption, "AR 2025 — p. 2");
  assert.equal(excerptView({ title: "AR 2025 — p. 12", src: "", quote: "Q", text: TX({}) })?.caption, "AR 2025 — p. 12 · p. 2");
  const v48 = excerptView({ title: "AR 2025", src: "", text: TX({ page: 34, page_start: 0, char_start: s, char_end: e }) }) as { caption: string; parts: { mark: string } };
  assert.equal(v48.caption, "AR 2025 · p. 34");
  assert.equal(v48.parts.mark, "revenue grew to €39bn");
});

const R = { runId: "r2", status: "Running" } as never;
const I = (kind: string) => ({ run_id: "r2", kind }) as never;
test("waiting counts conflicts", () => {
  assert.deepEqual(waiting([R], [I("value"), I("conflict"), I("conflict"), I("quarantined_document")]),
    { total: 4, groups: [{ label: "Conflicts", count: 2 }, { label: "Values to review", count: 1 }, { label: "Documents to check", count: 1 }] });
  assert.deepEqual(waiting([R], [I("value"), I("value")]), { total: 2, groups: [{ label: "Values to review", count: 2 }] });
});

test("flowReviewHref, readEach, earlierFailedLine", async () => {
  assert.equal(flowReviewHref({ kind: "profile", profile: "tnfd" }, "run_1"), "#/review/tnfd/run_1");
  assert.equal(flowReviewHref({ kind: "profile", profile: "financials" }, "run_1"), "#/review/financials/run_1");
  assert.equal(flowReviewHref({ kind: "schema" }, "run_1"), "#/review/extraction/run_1");
  assert.equal(flowReviewHref(null, "run_1"), "#/review/extraction/run_1");
  assert.deepEqual(await readEach(["a", "b", "c"], (id) => (id === "b" ? Promise.reject(new Error("x")) : Promise.resolve(id + "!"))),
    { loaded: [{ runId: "a", value: "a!" }, { runId: "c", value: "c!" }], failed: ["b"] });
  assert.equal(earlierFailedLine("run_7"), "Earlier results of run_7 could not be loaded.");
});

test("rfpId and refineDoc", () => {
  assert.equal(rfpId("12"), 12);
  assert.equal(rfpId("007"), 7);
  for (const x of ["abc", "", "1.5", "-1", "12abc", " 12", "NaN", undefined]) assert.equal(rfpId(x), null, String(x));
  assert.equal(refineDoc("rfp/abc"), null);
  assert.deepEqual(refineDoc("rfp/12"), { kind: "rfp", docId: "12" });
  assert.deepEqual(refineDoc("deck/abc"), { kind: "deck", docId: "abc" });
});
