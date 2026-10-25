import { test } from "node:test";
import assert from "node:assert/strict";
import { STATE_LABEL, dossierOfCandidate, shelvedBanner, stepLinkText, visibleDossiers } from "../src/lib/dossiers.ts";
import type { DossierItem } from "../src/types.ts";

const item = (over: Partial<DossierItem>): DossierItem => ({
  dossier_id: "dos_1", name: "n", status: "active", origin: "topic", run_id: null, theme_id: null, current_step: 2, created_at: "", ...over,
});

test("states read as the spec names them", () => {
  assert.deepEqual(
    (["skipped", "not_started", "not_built", "done", "waiting"] as const).map((s) => STATE_LABEL[s]),
    ["Skipped", "Not started", "Coming later", "Done", "Waiting"],
  );
});

test("the shelved banner names who, the day and why; an active dossier has none", () => {
  const d = { status: "shelved", shelved_by: "ana", shelved_at: "2026-10-25T09:12:00Z", shelve_reason: "No data" };
  assert.equal(shelvedBanner(d), "Shelved by ana on 2026-10-25: No data");
  assert.equal(shelvedBanner({ ...d, status: "active" }), null);
});

test("shelved dossiers are hidden until asked for", () => {
  const items = [item({ dossier_id: "a" }), item({ dossier_id: "b", status: "shelved" })];
  assert.deepEqual(visibleDossiers(items, false).map((d) => d.dossier_id), ["a"]);
  assert.deepEqual(visibleDossiers(items, true).map((d) => d.dossier_id), ["a", "b"]);
});

test("step 4 reads Find companies until a run exists", () => {
  assert.equal(stepLinkText(4, "#/theme"), "Find companies");
  assert.equal(stepLinkText(4, "#/theme/run_1"), "Open the run");
});

test("a candidate's dossier is found by its run and theme", () => {
  const items = [item({ dossier_id: "a", origin: "candidate", run_id: "r", theme_id: "t" }), item({ dossier_id: "b" })];
  assert.equal(dossierOfCandidate(items, "r", "t")?.dossier_id, "a");
  assert.equal(dossierOfCandidate(items, "r", "other"), undefined);
});
