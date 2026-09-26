import type { RuleGraph } from "../types";

// Starting graphs for the two rule editors (see RuleGraphEditor).

const node = (id: string, type: string, name: string, x: number, content?: object) => ({
  id,
  type,
  name,
  position: { x, y: 120 },
  ...(content ? { content } : {}),
});

export const STARTER: RuleGraph = {
  nodes: [
    node("input", "inputNode", "Row", 0),
    node("formulas", "expressionNode", "Formulas", 280, {
      expressions: [],
      passThrough: false,
      inputField: null,
      outputPath: null,
      executionMode: "single",
    }),
    node("output", "outputNode", "Calculated columns", 620),
  ],
  edges: [
    { id: "input-formulas", sourceId: "input", targetId: "formulas", type: "edge" },
    { id: "formulas-output", sourceId: "formulas", targetId: "output", type: "edge" },
  ],
};

// Tier rules start as "final tier = band": nothing changes until a row is
// added above the catch-all.
export const TIER_STARTER: RuleGraph = {
  nodes: [
    node("input", "inputNode", "Entity", 0),
    node("tiers", "decisionTableNode", "Tier rules", 280, {
      hitPolicy: "first",
      inputs: [{ id: "band_in", name: "Band", field: "band" }],
      outputs: [{ id: "tier_out", name: "Tier", field: "tier" }],
      rules: [{ _id: "keep_band", band_in: "", tier_out: "band" }],
      passThrough: false,
      inputField: null,
      outputPath: null,
      executionMode: "single",
    }),
    node("output", "outputNode", "Final tier", 620),
  ],
  edges: [
    { id: "input-tiers", sourceId: "input", targetId: "tiers", type: "edge" },
    { id: "tiers-output", sourceId: "tiers", targetId: "output", type: "edge" },
  ],
};

// --- red flags: a checkbox shortcut that writes tier-rule rows -------------
//
// The picker owns the rows and input columns whose ids start with "flag_" in
// the "tiers" decision table, one row per flag, placed first so a knock-out
// wins over the catch-all. Its state is read back from the same table, so
// the canvas and the picker can never disagree.

const FLAG = "flag_";

type Column = { id: string; name: string; field: string };
type Row = Record<string, string>;
type Table = { inputs: Column[]; outputs: Column[]; rules: Row[] };

/** The name an expression uses for a column, as the backend aliases it. */
export const slugify = (column: string) => column.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");

function tiersTable(graph: RuleGraph): Table | null {
  const node = graph.nodes.find((n) => n.id === "tiers" && n.type === "decisionTableNode");
  const table = node?.content as Table | undefined;
  return table && table.outputs.some((o) => o.field === "tier") ? table : null;
}

/** Selected flag columns and their target tier; null when the tier rules
 * have no picker-compatible table (built by hand on the canvas). */
export function readRedFlags(graph: RuleGraph | null | undefined): { columns: string[]; tier: number | null } | null {
  if (!graph) return { columns: [], tier: null };
  const table = tiersTable(graph);
  if (!table) return null;
  const tierOut = table.outputs.find((o) => o.field === "tier")!.id;
  const first = table.rules.find((r) => r._id.startsWith(FLAG));
  return {
    columns: table.inputs.filter((c) => c.id.startsWith(FLAG)).map((c) => c.name),
    tier: first ? Number(first[tierOut]) || null : null,
  };
}

/** The tier graph with exactly these flags sending an entity to `tier`.
 * Rows the user added by hand are kept, after the flag rows. */
export function writeRedFlags(graph: RuleGraph | null | undefined, columns: string[], tier: number): RuleGraph | null {
  if (!graph && columns.length === 0) return null;
  const next: RuleGraph = structuredClone(graph ?? TIER_STARTER);
  const table = tiersTable(next);
  if (!table) return graph ?? null;

  table.inputs = [...table.inputs.filter((c) => !c.id.startsWith(FLAG)), ...columns.map((c) => ({ id: FLAG + slugify(c), name: c, field: slugify(c) }))];
  if (!table.outputs.some((o) => o.field === "note")) table.outputs = [...table.outputs, { id: "note_out", name: "Note", field: "note" }];
  const tierOut = table.outputs.find((o) => o.field === "tier")!.id;
  const noteOut = table.outputs.find((o) => o.field === "note")!.id;
  const cells = [...table.inputs, ...table.outputs].map((c) => c.id);
  const complete = (row: Row): Row => ({ _id: row._id, ...Object.fromEntries(cells.map((id) => [id, row[id] ?? ""])) });

  table.rules = [
    ...columns.map((c) =>
      complete({ _id: FLAG + slugify(c), [FLAG + slugify(c)]: "true", [tierOut]: String(tier), [noteOut]: `'Red flag: ${c.replace(/'/g, "")}'` }),
    ),
    ...table.rules.filter((r) => !r._id.startsWith(FLAG)).map(complete),
  ];
  return next;
}
