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
