import test from "node:test";
import assert from "node:assert/strict";
import { accessFor, decisionBody, mergeDecided, nextAwaiting, recordedFrom, rowKey, sortQueue, toRow } from "../src/pages/lab/tapeData.ts";
import type { QueueItem } from "../src/components/RunReviewList";
import type { ReviewDecision, ReviewItem } from "../src/types";
import type { Me } from "../src/lib/reviewKeys.ts";

const analyst: Me = { user_id: "u1", name: "Ana", role: "analyst" };
const approver: Me = { ...analyst, role: "approver" };
const viewer: Me = { ...analyst, role: "viewer" };

function mk(key: string, over: Partial<ReviewItem> = {}, payload: Record<string, unknown> = {}): QueueItem {
  const review: ReviewItem = {
    item_key: key, kind: "value", run_id: "r1", run_type: "extraction", payload, state: "pending", escalated: false, high_risk: false, decision: null, ...over,
  };
  return { kind: review.run_type, runId: review.run_id, item: { ...payload, item_key: key }, review };
}
const ctx = { etag: "E1", blind: false, decisions: [] as ReviewDecision[] };

test("sortQueue: lowest confidence first, field confidence read, missing last, stable", () => {
  const a = mk("a", {}, { confidence: 0.9 });
  const b = mk("b", {}, { field: { confidence: 0.2 } });
  const c = mk("c");
  const d = mk("d");
  const input = [a, c, b, d];
  assert.deepEqual(sortQueue(input).map((q) => q.review.item_key), ["b", "a", "c", "d"]);
  assert.equal(input[0], a);
});

test("toRow maps real fields, falls back for names, en-dash cells are null", () => {
  const r = toRow(mk("C1:net_zero_target", {}, { queued_at: "2026-10-05T09:30:00Z", company_id: "C1", field: { field_name: "Revenue", value: 5, unit: "EUR", value_state: "found", confidence: 0.4 }, reason_codes: ["low_conf"], route_reasons: ["low_conf", "x"] }), analyst);
  assert.equal(r.queued, "10-05 09:30");
  assert.equal(r.entity, "C1");
  assert.equal(r.field, "Revenue");
  assert.equal(r.proposed, "5 EUR");
  assert.equal(r.confidence, 0.4);
  assert.deepEqual(r.reasons, ["low_conf", "x"]);
  assert.equal(r.awaiting, true);
  const bare = toRow(mk("C1:net_zero_target", { kind: "identity" }), analyst);
  assert.equal(bare.entity, "C1 · net zero target");
  assert.equal(bare.queued, null);
  assert.equal(bare.proposed, null);
  assert.equal(bare.confidence, null);
  assert.equal(bare.href, "#/review/extraction/r1");
});

test("accessFor follows decideBlock and decisionChoices", () => {
  assert.deepEqual(accessFor(mk("a"), analyst), { ok: true, actions: ["approve", "reject", "escalate"] });
  assert.deepEqual(accessFor(mk("a"), viewer), { ok: false, reason: "Sign in as an analyst or approver to decide." });
  assert.deepEqual(accessFor(mk("a"), null), { ok: false, reason: "Sign in as an analyst or approver to decide." });
  assert.deepEqual(accessFor(mk("a", { escalated: true }), analyst), { ok: false, reason: "Escalated; an approver decides." });
  const mine = mk("a", { state: "first_done", decision: { item_key: "a", decision: "approve", mine: true, decided_at: "" } });
  assert.deepEqual(accessFor(mine, analyst), { ok: false, reason: "Waiting for a second reviewer." });
  const dis = accessFor(mk("a", { state: "disagreed" }), approver);
  assert.deepEqual(dis, { ok: true, actions: ["approve", "reject"] });
  assert.equal(accessFor(mk("a", { state: "final" }), analyst).ok, false);
  assert.equal(accessFor(mk("a"), analyst, true).ok, false);
});

test("legacy kinds are read-only, extraction other is decidable", () => {
  const legacy = mk("a", { kind: "other", run_type: "theme" });
  assert.equal(accessFor(legacy, approver).ok, false);
  assert.equal(toRow(legacy, approver).readOnly, true);
  assert.equal(toRow(legacy, approver).awaiting, false);
  assert.deepEqual(accessFor(mk("a", { kind: "other" }), analyst), { ok: true, actions: ["approve", "reject", "escalate"] });
});

test("citation kinds are flagged for the Review Queue link", () => {
  assert.equal(toRow(mk("a"), analyst).citation, true);
  assert.equal(toRow(mk("a", { kind: "identity" }), analyst).citation, false);
});

test("decisionBody: approve, reject, escalate bodies match ReviewControls", () => {
  const q = mk("a");
  assert.deepEqual(decisionBody("approve", q, ctx), { decision: "approve", reason_code: "confirmed", corrected_value: null, correction_citation: null, comment: null, context_etag: "E1" });
  assert.deepEqual(decisionBody("reject", q, ctx, { reason: "wrong_value", comment: "  off by 10x " }), { decision: "reject", reason_code: "wrong_value", corrected_value: null, correction_citation: null, comment: "off by 10x", context_etag: "E1" });
  assert.equal(decisionBody("escalate", q, ctx, { reason: "needs_expert", comment: "" })?.comment, null);
  assert.equal(decisionBody("reject", q, ctx), null);
  assert.equal(decisionBody("reject", q, ctx, { reason: "confirmed", comment: "" }), null);
});

test("decisionBody: a second reviewer approving a first correction agrees with it", () => {
  const first: ReviewDecision = { item_key: "a", decision: "correct", reason_code: "wrong_value", corrected_value: { value: 7 }, correction_citation: { doc_id: "d", doc_type: "ar", quote: "q" } as ReviewDecision["correction_citation"], comment: "c", decided_at: "" };
  const q = mk("a", { state: "first_done", decision: first });
  const b = decisionBody("approve", q, { ...ctx, decisions: [first] });
  assert.equal(b?.decision, "correct");
  assert.equal(b?.reason_code, "wrong_value");
  assert.deepEqual(b?.corrected_value, { value: 7 });
  assert.equal(b?.context_etag, "E1");
});

test("mergeDecided: swaps fresh items, marks decided only when the run drops the row", () => {
  const a = mk("a"), b = mk("b");
  const rec = recordedFrom(decisionBody("approve", a, ctx)!, analyst, "a", "pending", new Date(0));
  assert.equal(rec.mine, true);
  assert.equal(rec.step, "first");
  const aNow = mk("a", { state: "first_done" });
  const kept = mergeDecided([a, b], a, rec, [aNow]);
  assert.equal(kept.items[0], aNow);
  assert.equal(kept.items[1], b);
  assert.equal(kept.decided, null);
  assert.equal(mergeDecided([a, b], a, rec, []).decided, rec);
  assert.equal(mergeDecided([a, b], a, rec, null).decided, rec);
  assert.equal(mergeDecided([a], mk("a", { kind: "other" }), rec, [aNow]).decided, rec);
  assert.equal(rowKey(a), "r1/a");
});

test("decided rows show the decision with role and (you); nextAwaiting skips decided rows", () => {
  const dec: ReviewDecision = { item_key: "a", decision: "approve", role: "approver", mine: true, decided_at: "" };
  const r = toRow(mk("a", { state: "final", decision: dec }), analyst);
  assert.equal(r.decision, "approved by approver (you)");
  assert.equal(r.awaiting, false);
  assert.equal(toRow(mk("a"), analyst, dec).state, "final");
  assert.equal(nextAwaiting([{ awaiting: true }, { awaiting: false }, { awaiting: true }], 0), 2);
  assert.equal(nextAwaiting([{ awaiting: true }, { awaiting: false }], 0), 0);
});
