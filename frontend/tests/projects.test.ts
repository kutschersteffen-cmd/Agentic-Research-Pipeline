import test from "node:test";
import assert from "node:assert/strict";
import { apiMessage, createAndOpen, embeddable, saveBody } from "../src/lib/projects.ts";

const dash = (id: number | null, slug = "arp-p--a") => ({ id, slug, title: slug, published: true, status: "created" });

test("createAndOpen calls create, upload once per file, then open, in order", async () => {
  const calls: string[] = [];
  const api = {
    createProject: async () => (calls.push("create"), { id: "p1" }),
    uploadProjectData: async (_id: string, f: File, n: number) => (calls.push(`upload:${f.name}:${n}`), {}),
    openProject: async (id: string) => (calls.push(`open:${id}`), { data: [], dashboards: [dash(1)] }),
  };
  const files = [new File(["a"], "a.xlsx"), new File(["b"], "b.xlsx")];
  const r = await createAndOpen(api, { name: "P", notionalEur: 5, files });
  assert.deepEqual(calls, ["create", "upload:a.xlsx:5", "upload:b.xlsx:5", "open:p1"]);
  assert.equal(r.result.dashboards.length, 1);
});

test("createAndOpen stops at a failing upload and never opens", async () => {
  const calls: string[] = [];
  const api = {
    createProject: async () => ({ id: "p1" }),
    uploadProjectData: async () => { throw new Error("422: bad file"); },
    openProject: async () => (calls.push("open"), { data: [], dashboards: [] }),
  };
  await assert.rejects(createAndOpen(api, { name: "P", notionalEur: 1, files: [new File(["a"], "a.xlsx")] }));
  assert.deepEqual(calls, []);
});

test("apiMessage drops the status prefix and keeps our message", () => {
  assert.equal(apiMessage(new Error("502: Opening the project failed at data: boom")), "Opening the project failed at data: boom");
});

test("saveBody sends the designer's plan; null without a plan or dashboard", () => {
  const plan = { title: "T", goal: "", charts: [] };
  const r = { dashboard_id: 3, slug: "s", url: null, plan, rejected: [], clarification_needed: null };
  assert.deepEqual(saveBody(r), { title: "T", plan });
  assert.equal(saveBody({ ...r, plan: null }), null);
  assert.equal(saveBody({ ...r, dashboard_id: null }), null);
  assert.equal(saveBody(null), null);
});

test("embeddable drops dashboards without a Superset id", () => {
  assert.deepEqual(embeddable([dash(1), dash(null, "arp-p--x")]).map((d) => d.id), [1]);
});

import { formatValidationErrors, initialPicker, isOther, projectGroups, reducePicker } from "../src/lib/projects.ts";
import type { PickerEvent, PickerState } from "../src/lib/projects.ts";

const item = (id: number, slug: string) => ({ id, slug, title: slug, published: true });
const run = (s: PickerState, ...es: PickerEvent[]) => es.reduce(reducePicker, s);
const standard = [item(1, "arp-a"), item(2, "arp-risk-exposure"), item(3, "arp-p--x")];

test("create path: project set before open, ends with the project's dashboards and the first selected", async () => {
  const log: string[] = [];
  let s: PickerState = run(initialPicker, { type: "list", items: standard });
  const api = {
    createProject: async () => ({ id: "p" }),
    uploadProjectData: async () => ({}),
    openProject: async () => ({ data: [], dashboards: [dash(null, "arp-p--skip"), dash(3, "arp-p--x"), dash(4, "arp-p--y")] }),
  };
  const r = await createAndOpen(api, { name: "P", notionalEur: 1, files: [new File(["a"], "a.xlsx")] }, (id) => {
    log.push("created");
    s = reducePicker(s, { type: "select", project: id });
  });
  s = reducePicker(s, { type: "opened", dashboards: r.result.dashboards });
  assert.deepEqual(log, ["created"]);
  assert.equal(s.project, "p");
  assert.deepEqual(s.projectDashboards?.map((d) => d.id), [3, 4]);
  assert.equal(s.selectedId, 3);
});

test("back to Standard resets the selection to the standard default", () => {
  const s = run(
    initialPicker,
    { type: "list", items: standard },
    { type: "select", project: "p" },
    { type: "opened", dashboards: [dash(3, "arp-p--x")] },
    { type: "select", project: null },
  );
  assert.equal(s.project, null);
  assert.equal(s.selectedId, 2);
});

test("a list reload in project mode leaves the project selection alone", () => {
  const s = run(
    initialPicker,
    { type: "list", items: standard },
    { type: "select", project: "p" },
    { type: "opened", dashboards: [dash(3, "arp-p--x")] },
    { type: "list", items: [...standard, item(9, "arp-new")], preferId: 9 },
  );
  assert.equal(s.selectedId, 3);
  assert.equal(s.project, "p");
  assert.equal(s.standard?.length, 4);
  assert.deepEqual(s.projectDashboards?.map((d) => d.id), [3]);
});

test("projectGroups: others exclude project slugs and ids already in the project; isOther picks only group two", () => {
  const mine = [item(3, "arp-p--x"), item(5, "arp-imported")];
  const g = projectGroups("p", mine, [...standard, item(5, "arp-imported"), item(6, "arp-hand")]);
  assert.deepEqual(g.others.map((d) => d.id), [1, 2, 6]);
  assert.deepEqual(g.union.map((d) => d.id), [3, 5, 1, 2, 6]);
  assert.equal(isOther(g.others, 6), true);
  assert.equal(isOther(g.others, 3), false);
  assert.deepEqual(projectGroups("p", [], null).union, []);
});

test("saved adds the exported dashboard to the project and selects it", () => {
  const s = run(
    initialPicker,
    { type: "select", project: "p" },
    { type: "opened", dashboards: [dash(3, "arp-p--x")] },
    { type: "saved", item: item(6, "arp-hand") },
  );
  assert.deepEqual(s.projectDashboards?.map((d) => d.id), [3, 6]);
  assert.equal(s.selectedId, 6);
});

test("formatValidationErrors handles pydantic objects and the plan validator's plain strings", () => {
  assert.equal(formatValidationErrors(["unknown dataset x", "too many charts"]), "unknown dataset x; too many charts");
  assert.equal(
    formatValidationErrors([{ loc: ["body", "plan", "title"], msg: "Value error, bad" }, { msg: "oops" }]),
    "plan › title: bad; oops",
  );
});

test("opened is ignored in Standard mode (a failed create must not change the picker)", () => {
  const s = run(initialPicker, { type: "list", items: standard });
  assert.equal(reducePicker(s, { type: "opened", dashboards: [] }), s);
});

test("a failed open in project mode empties the project list and selects nothing", () => {
  const s = run(
    initialPicker,
    { type: "list", items: standard },
    { type: "select", project: "p" },
    { type: "opened", dashboards: [dash(3, "arp-p--x")] },
    { type: "select", project: "p" },
    { type: "opened", dashboards: [] },
  );
  assert.deepEqual(s.projectDashboards, []);
  assert.equal(s.selectedId, null);
});
