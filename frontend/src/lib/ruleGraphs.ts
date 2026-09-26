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
