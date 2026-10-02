import test from "node:test";
import assert from "node:assert/strict";
import { jobLabel, jobsToStart, removeJob, startJobs, startsText, toggleProfile, worstStatus } from "../src/lib/jobs.ts";
import type { BuiltInJob, CustomJob, Job } from "../src/lib/jobs.ts";
import type { DataPointSchema } from "../src/types.ts";

const b = (id: BuiltInJob["id"]): Job => ({ id, profile: id });
const schema = (name: string) => ({ name }) as DataPointSchema;
const cu = (id: string, s: DataPointSchema | null = null): CustomJob => ({ id, profile: "custom", schema: s, request: "" });
const ids = (jobs: Job[]) => jobs.map((j) => j.id);
const noId = () => "custom:9";

test("labels", () => {
  assert.equal(jobLabel(b("financials")), "Financials");
  assert.equal(jobLabel(cu("custom:1", schema("Green capex"))), "Custom: Green capex");
  assert.equal(jobLabel(cu("custom:1")), "Custom (no schema yet)");
});

test("toggle adds and removes", () => {
  const added = toggleProfile([b("financials")], "tnfd", noId);
  assert.deepEqual(ids(added.jobs), ["financials", "tnfd"]);
  assert.equal(added.error, null);
  assert.deepEqual(ids(toggleProfile(added.jobs, "financials", noId).jobs), ["tnfd"]);
});

test("cannot untick last", () => {
  const jobs = [b("financials")];
  const r = toggleProfile(jobs, "financials", noId);
  assert.equal(r.error, "Pick at least one profile");
  assert.equal(r.jobs, jobs);
});

test("custom toggle", () => {
  const r = toggleProfile([b("financials")], "custom", noId);
  assert.equal(r.jobs.length, 2);
  assert.ok(r.jobs[1].id.startsWith("custom:"));
  const two = [b("financials"), cu("custom:1"), cu("custom:2")];
  assert.deepEqual(ids(toggleProfile(two, "custom", noId).jobs), ["financials"]);
});

test("removeJob last refused", () => {
  const jobs = [b("tnfd")];
  const r = removeJob(jobs, "tnfd");
  assert.equal(r.error, "Pick at least one profile");
  assert.equal(r.jobs, jobs);
  assert.deepEqual(ids(removeJob([b("tnfd"), b("financials")], "tnfd").jobs), ["financials"]);
});

test("jobsToStart skips unready and started", () => {
  const jobs = [b("financials"), b("tnfd"), cu("custom:1"), cu("custom:2", schema("X"))];
  assert.deepEqual(ids(jobsToStart(jobs, { financials: "r1" })), ["tnfd", "custom:2"]);
});

test("startJobs continues after a failure", async () => {
  const jobs = [b("financials"), b("tnfd"), cu("custom:1", schema("X"))];
  const order: string[] = [];
  const r = await startJobs(jobs, async (j) => {
    order.push(j.id);
    if (j.id === "tnfd") throw new Error("boom");
    return `run-${j.id}`;
  });
  assert.deepEqual(order, ["financials", "tnfd", "custom:1"]);
  assert.deepEqual(r.started, { financials: "run-financials", "custom:1": "run-custom:1" });
  assert.deepEqual(r.errors, { tnfd: "boom" });
});

test("startsText", () => {
  assert.equal(startsText(3, 50), "Starts 3 runs × 50 companies");
  assert.equal(startsText(1, 1), "Starts 1 run × 1 company");
});

test("worstStatus picks the most urgent state", () => {
  assert.equal(worstStatus(["done", "running"]), "running");
  assert.equal(worstStatus(["review", "failed"]), "failed");
  assert.equal(worstStatus([]), "idle");
});
