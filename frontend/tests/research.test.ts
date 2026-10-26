import { test } from "node:test";
import assert from "node:assert/strict";
import { CATEGORY_LABEL, NOTE_SECTIONS, canPropose, canUpload, canWriteNote, planOpen, unreadLines } from "../src/lib/research.ts";
import { stepLinkText } from "../src/lib/dossiers.ts";
import type { ResearchNote, ResearchRound } from "../src/types.ts";

const note = (over: Partial<ResearchNote>): ResearchNote => ({
  status: "written", dropped_items: 0, unread_sources: [], written_at: null, approved_by: null, approved_at: null,
  rejected_by: null, rejected_at: null, reject_reason: null, error: null,
  sections: { risks: [], opportunities: [], financial_relevance: [], growth_potential: [], transmission_channels: [] }, ...over,
});
const round = (over: Partial<ResearchRound>): ResearchRound => ({
  round: 1, taxonomy_version: 1, plan_status: "proposed", proposal_run_id: null, plan_approved_by: null, plan_approved_at: null,
  sources: [], note: null, note_run_id: null, ...over,
});

test("categories and headings read as the spec names them", () => {
  assert.deepEqual(Object.values(CATEGORY_LABEL), ["Intergovernmental agency", "Government or official statistics", "Central bank or regulator", "Academic research"]);
  assert.deepEqual(NOTE_SECTIONS.map(([, h]) => h), ["Risks", "Opportunities", "Financial relevance", "Growth potential", "Transmission channels"]);
  assert.equal(stepLinkText(3, "#/themes/d/research"), "Open research");
});

test("which actions a round allows", () => {
  assert.equal(canPropose(undefined), true);
  assert.equal(canPropose(round({})), false);
  assert.equal(canPropose(round({ plan_status: "proposal_failed" })), true);
  assert.equal(canPropose(round({ plan_status: "approved", note: note({ status: "approved" }) })), true);
  assert.equal(planOpen(round({ plan_status: "approved" })), false);
  assert.equal(canWriteNote(round({ plan_status: "approved" })), true);
  assert.equal(canWriteNote(round({ plan_status: "approved", note: note({}) })), false);
  assert.equal(canUpload(round({ plan_status: "approved", note: note({ status: "rejected" }) })), true);
  assert.equal(canUpload(round({ note: note({ status: "approved" }) })), false);
});

test("unread sources are named by title", () => {
  const r = round({
    sources: [{ source_id: "src_1", title: "J. Energy Econ paper", publisher: "p", url: "u", category: "academic", why: "w", how: "h", added_by: "model", file: null }],
    note: note({ unread_sources: [{ source_id: "src_1", reason: "fetch failed" }] }),
  });
  assert.deepEqual(unreadLines(r), ["Not read: J. Energy Econ paper (fetch failed)"]);
});
