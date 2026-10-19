import test from "node:test";
import assert from "node:assert/strict";
import { errorDetail, layersSummary, todayUtc, viaLabel } from "../src/lib/themeLayers.ts";
import type { ThemeLayerRow, ThemeLayers } from "../src/types.ts";

const row = (issuer_key: string, name: string, l2_via: string[] | null = null): ThemeLayerRow => ({
  issuer_key, name, in_run: true, l1: null, l2: null, l3: null, score: null, pure_play: false, status: "scored", rank: null, l2_via,
});

test("the summary line names weights, decay and as-of date", () => {
  const r: ThemeLayers = {
    run_id: "R", as_of: "2024-06-30", weights: { w1: 0.45, w2: 0.35, w3: 0.2 }, decay: 0.85, max_hops: 2, pure_play_threshold: 0.5, rows: [],
  };
  assert.equal(layersSummary(r), "Weights 0.45 / 0.35 / 0.20 · decay 0.85 · as of 2024-06-30");
});

test("via joins names along the path", () => {
  const rows = [row("a", "A"), row("s1", "S1", ["s1", "a"]), row("s2", "S2", ["s2", "s1", "a"])];
  assert.equal(viaLabel(rows[1], rows), "S1 → A");
  assert.equal(viaLabel(rows[2], rows), "S2 → S1 → A");
  assert.equal(viaLabel(rows[0], rows), "");
});

test("via falls back to the key for a company not listed", () => {
  assert.equal(viaLabel(row("s1", "S1", ["s1", "zz"]), []), "S1 → zz");
});

test("errorDetail drops the status prefix", () => {
  assert.equal(errorDetail(new Error("503: company graph not configured: set ARP_NEO4J_URI")), "company graph not configured: set ARP_NEO4J_URI");
  assert.equal(errorDetail(new Error("Failed to fetch")), "Failed to fetch");
});

test("today is the UTC date", () => {
  assert.equal(todayUtc(), new Date().toISOString().slice(0, 10));
});
