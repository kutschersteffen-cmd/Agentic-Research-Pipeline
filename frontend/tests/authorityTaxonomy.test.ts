import { test, mock } from "node:test";
import assert from "node:assert/strict";
import {
  canBuild, editText, initialSelection, prefill, saveThenAccept, sourcesBody, startBody, startPolling, viewFor, THEME_KEYS,
} from "../src/lib/authorityTaxonomy.ts";
import type { AuthorityRunState } from "../src/types.ts";

const cand = (url: string, o: object = {}) =>
  ({ url, title: url, source_type: "agency_report", summary: "", reason: "", fetchable: true, covers: [], from_library: false, ...o });
const run = (o: Partial<AuthorityRunState> = {}) =>
  ({ run_id: "r", stage: "awaiting_sources", theme_name: "Hydrogen", theme_key: "hydrogen", scope: "S1", guidance: "G1", value_chain: true,
    candidates: [], notes: "", error: null, selection: null, ...o }) as AuthorityRunState;
const form = { theme_name: "Hydrogen", theme_key: "hydrogen", scope: "S1", guidance: "G1", value_chain: true };

test("start form: name required, body exact", () => {
  assert.deepEqual(startBody({ ...form, theme_name: "  " }), { error: "Theme name is required" });
  assert.equal(JSON.stringify((startBody(form) as { body: unknown }).body), '{"theme_name":"Hydrogen","theme_key":"hydrogen","scope":"S1","guidance":"G1","value_chain":true}');
  assert.equal(THEME_KEYS.length, 10);
});

test("sources body: ticked first, then added URLs; build needs a selection and no running upload", () => {
  const s = { ticked: [], urls: ["u1"], files: [{ name: "n", path: "P" }], uploading: 0 };
  assert.deepEqual(sourcesBody(s), { urls: ["u1"], files: ["P"] });
  assert.deepEqual(sourcesBody({ ...s, ticked: ["t"] }).urls, ["t", "u1"]);
  assert.equal(canBuild({ ...s, uploading: 1 }), false);
  assert.equal(canBuild({ ticked: [], urls: [], files: [], uploading: 0 }), false);
  assert.equal(canBuild(s), true);
});

test("initial selection restores a saved selection, else ticks fetchable library candidates", () => {
  const candidates = [cand("A"), cand("B", { from_library: true })];
  const restored = initialSelection(run({ candidates, selection: { urls: ["A", "u9"], files: ["/d/_authority/n.txt"] } }));
  assert.deepEqual([restored.ticked, restored.urls, restored.files], [["A"], ["u9"], [{ name: "n.txt", path: "/d/_authority/n.txt" }]]);
  assert.deepEqual(initialSelection(run({ candidates })).ticked, ["B"]);
  assert.deepEqual(initialSelection(run({ candidates: [cand("C", { from_library: true, fetchable: false })] })).ticked, []);
});

const fakeDoc = (state = "visible") => {
  const handlers = new Set<() => void>();
  const doc = {
    visibilityState: state as DocumentVisibilityState,
    addEventListener: (_: string, h: () => void) => handlers.add(h),
    removeEventListener: (_: string, h: () => void) => handlers.delete(h),
  };
  return { doc: doc as unknown as Pick<Document, "visibilityState" | "addEventListener" | "removeEventListener">, set: (s: string) => { (doc as { visibilityState: string }).visibilityState = s; handlers.forEach((h) => h()); } };
};
const settle = async () => { for (let i = 0; i < 5; i++) await Promise.resolve(); };

test("polling: loads at 0, then every 3 s while working, stops when done", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const stages = ["discovering", "discovering", "discovering", "awaiting_sources"];
    let calls = 0;
    const stop = startPolling(async () => run({ stage: stages[Math.min(calls++, 3)] as never }), () => {}, fakeDoc().doc);
    for (let s = 0; s < 5; s++) { await settle(); mock.timers.tick(3000); }
    await settle();
    assert.equal(calls, 4);
    stop();
  } finally { mock.timers.reset(); }
});

test("polling: paused while hidden, one poll at once when visible again", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    let calls = 0;
    const d = fakeDoc();
    const stop = startPolling(async () => { calls++; return run({ stage: "discovering" }); }, () => {}, d.doc);
    await settle();
    d.set("hidden");
    for (let s = 0; s < 4; s++) { await settle(); mock.timers.tick(3000); }
    await settle();
    assert.equal(calls, 1);
    d.set("visible");
    await settle();
    assert.equal(calls, 2);
    stop();
  } finally { mock.timers.reset(); }
});

test("editText keeps the citations", () => {
  const item = { text: "old", citations: [{ quote: "q", source_url: "u", location: "l" }] };
  const out = editText(item, { text: "new" });
  assert.equal(out.text, "new");
  assert.equal(out.citations, item.citations);
});

test("accept saves first, and stops when the save fails", async () => {
  const order: string[] = [];
  const out = await saveThenAccept(true, async () => { order.push("save"); }, async () => { order.push("accept"); return { taxonomy_id: "T" }; });
  assert.deepEqual([order, out], [["save", "accept"], { taxonomy_id: "T" }]);
  let accepted = false;
  await assert.rejects(saveThenAccept(true, async () => { throw new Error("422: x"); }, async () => { accepted = true; return { taxonomy_id: "T" }; }), /422: x/);
  assert.equal(accepted, false);
});

test("prefill and views", () => {
  assert.deepEqual(prefill(run()), form);
  assert.equal(viewFor(null), "not_found");
  assert.deepEqual(["discovering", "awaiting_sources", "awaiting_review", "accepted", "failed"].map((stage) => viewFor(run({ stage: stage as never }))),
    ["working", "sources", "review", "accepted", "ended"]);
});
