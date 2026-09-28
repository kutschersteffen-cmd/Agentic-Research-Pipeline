import type { PipelineShape } from "../types";

/** Columns by longest path from the entry, so every edge points right;
 * within a column the main path sits on top and the early exits
 * ("No evidence", "Answer failed") below it. */
export function layoutPipeline(shape: PipelineShape, colWidth: number, rowHeight: number): Record<string, { x: number; y: number }> {
  const depth: Record<string, number> = {};
  const entry = shape.nodes[0]?.id;
  if (!entry) return {};
  depth[entry] = 0;
  // Longest path on a DAG: relax every edge as many times as there are nodes.
  for (let i = 0; i < shape.nodes.length; i++) {
    for (const e of shape.edges) {
      if (depth[e.source] !== undefined && (depth[e.target] ?? -1) < depth[e.source] + 1) depth[e.target] = depth[e.source] + 1;
    }
  }
  const columns: Record<number, string[]> = {};
  for (const n of shape.nodes) (columns[depth[n.id] ?? 0] ??= []).push(n.id);
  const positions: Record<string, { x: number; y: number }> = {};
  for (const [d, ids] of Object.entries(columns)) {
    ids.sort((a, b) => Number(a.startsWith("finalize")) - Number(b.startsWith("finalize")));
    ids.forEach((id, row) => (positions[id] = { x: Number(d) * colWidth, y: row * rowHeight }));
  }
  return positions;
}
