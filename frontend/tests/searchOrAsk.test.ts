import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { WORKSPACES, moreLinks, rowLinks } from "../src/lib/processes.ts";

// ui-trim-workspaces (docs/superpowers/specs/2026-11-22-ui-trim-workspaces.md).
const read = (p: string) => readFileSync(new URL(p, import.meta.url), "utf8");

test("AC-6: the palette offers Ask ARP only when the user can ask", () => {
  assert.match(read("../src/App.tsx"), /onAsk=\{canAsk \?[\s\S]*?: undefined\}/);
  assert.match(read("../src/components/CommandPalette.tsx"), /const askRow = onAsk && question \?/);
});

test("Strategy row and its More menu", () => {
  const s = WORKSPACES.find((w) => w.id === "rdLab")!;
  assert.deepEqual(rowLinks(s).map(([, l]) => l), ["Strategy", "Design a strategy", "Themes", "Decision Studio", "Portfolio Builder"]);
  assert.deepEqual(moreLinks(s).map(([, l]) => l), ["Taxonomy Library", "Thematic Universe", "Strategy Replication", "Signals workbench", "Value Chain Explorer"]);
});
