import test from "node:test";
import assert from "node:assert/strict";
import { whyLinks } from "../src/lib/whyLinks.ts";

const row = (entity_id: string, status = "scored", tier_name: string | null = "Tier 1") => ({ entity_id, name: entity_id, status, tier_name });
const snap = (snapshot_id: string, framework_id: string, framework_name: string, published_at: string, rows: ReturnType<typeof row>[]) =>
  ({ snapshot_id, framework_id, framework_name, published_at, rows });

test("AC-34 one link per framework, the newest snapshot", () => {
  const published = [
    snap("s_old", "fw_s", "S", "2026-10-29T10:00:00Z", [row("A", "scored", "Tier 3")]),
    snap("s_new", "fw_s", "S", "2026-10-30T10:00:00Z", [row("A", "scored", "Tier 1")]),
    snap("t_1", "fw_t", "T", "2026-10-30T09:00:00Z", [row("A", "scored", "Tier 2")]),
  ];
  assert.deepEqual(whyLinks("A", published), [
    { label: "Why: S Tier 1", snapshotId: "s_new", entityId: "A" },
    { label: "Why: T Tier 2", snapshotId: "t_1", entityId: "A" },
  ]);
});

test("a no-score row says so", () => {
  assert.deepEqual(whyLinks("C", [snap("s", "fw_s", "S", "2026-10-30T10:00:00Z", [row("C", "no_score", null)])]), [
    { label: "Why: S no score", snapshotId: "s", entityId: "C" },
  ]);
});

test("an issuer with no published row gets no link", () => {
  assert.deepEqual(whyLinks("Z", [snap("s", "fw_s", "S", "2026-10-30T10:00:00Z", [row("A")])]), []);
});
