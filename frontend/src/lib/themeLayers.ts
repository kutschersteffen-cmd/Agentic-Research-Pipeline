import type { ThemeLayerRow, ThemeLayers } from "../types.ts";

export function todayUtc(): string {
  return new Date().toISOString().slice(0, 10);
}

export function layersSummary(r: ThemeLayers): string {
  const { w1, w2, w3 } = r.weights;
  return `Weights ${[w1, w2, w3].map((w) => w.toFixed(2)).join(" / ")} · decay ${r.decay.toFixed(2)} · as of ${r.as_of}`;
}

/** The Layer 2 path as company names, supplier first; "" when the row has no Layer 2. */
export function viaLabel(row: ThemeLayerRow, rows: ThemeLayerRow[]): string {
  const names = new Map(rows.map((r) => [r.issuer_key, r.name]));
  return (row.l2_via ?? []).map((k) => (k === row.issuer_key ? row.name : names.get(k) ?? k)).join(" → ");
}

/** An API error's message without its "NNN: " status prefix. */
export function errorDetail(e: unknown): string {
  return String(e instanceof Error ? e.message : e).replace(/^\d{3}: /, "");
}
