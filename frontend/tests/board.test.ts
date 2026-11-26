import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import {
  boardNeedsReload, csvToTable, diagramWidth, MIN_DIAGRAM_SCALE, detailOf, diagramGroups, diagramType, download, downloadName, DRAW_PLACEHOLDER, editedSource, editText,
  EMPTY_BOARD, firstLine, groupLabel, GROUP_SLOTS, hasEmphasis, liveLabel, menuItems, parseInline, parseMarkdown, svgDataUrl, themedSource,
  tileChange, tileValue, toCsv, unverifiedLine, type BoardBlock, type DiagramTheme,
} from "../src/lib/board.ts";

// Board tab of the Agent screen (docs/superpowers/specs/2026-11-22-agent-board.md, slice 3).

const block = (over: Partial<BoardBlock>): BoardBlock => ({
  id: "b1", kind: "note", title: "T", source: "", position: 0, version: 1, origin: "person", unverified: [], rendered: null,
  live: false, live_error: null, live_step: null, ...over,
});
const FLOW_F = "flowchart LR\n  a[Build universe] --> b[Extract]\n  b --> c[Report]";
const MIND_M = "mindmap\n  root((Grow newsletter))\n    Topics\n    LinkedIn";
const GROUPED_G = "flowchart LR\n  a[Find flat]:::Housing --> b[Give notice]:::Berlin\n  b --> c[Register]:::Munich\n  class b emphasis";

test("the empty board and the draw field read as the spec spells them (AC-54)", () => {
  assert.equal(EMPTY_BOARD, "Nothing on the board yet. Ask for a chart, diagram, table or checklist.");
  assert.equal(DRAW_PLACEHOLDER, "Ask the agent to draw something…");
});

test("Not in ARP data lists the first 10 numbers, then how many more (AC-18, AC-18b)", () => {
  assert.equal(unverifiedLine([]), null);
  assert.equal(unverifiedLine([0.435]), "Not in ARP data: 0.435");
  const twelve = Array.from({ length: 12 }, (_, i) => 101 + i);
  assert.equal(unverifiedLine(twelve), "Not in ARP data: 101, 102, 103, 104, 105, 106, 107, 108, 109, 110 and 2 more");
  assert.equal(unverifiedLine(twelve.slice(0, 10)), "Not in ARP data: 101, 102, 103, 104, 105, 106, 107, 108, 109, 110");
});

test("the ⋯ menu drops Move up on the first block, Move down on the last, Undo at version 1 (AC-25b)", () => {
  assert.deepEqual(menuItems(0, 1, 1), ["Edit", "Change with agent…", "Download", "Delete"]);
  assert.deepEqual(menuItems(0, 2, 2), ["Edit", "Change with agent…", "Move down", "Undo last change", "Download", "Delete"]);
  assert.deepEqual(menuItems(1, 3, 1), ["Edit", "Change with agent…", "Move up", "Move down", "Download", "Delete"]);
  assert.deepEqual(menuItems(2, 3, 1), ["Edit", "Change with agent…", "Move up", "Download", "Delete"]);
});

test("a live block's label names its step, or just Live (AC-52)", () => {
  assert.equal(liveLabel({ live: true, live_step: 1 }), "Live · step 1");
  assert.equal(liveLabel({ live: true, live_step: null }), "Live");
  assert.equal(liveLabel({ live: false, live_step: null }), null);
});

test("download names replace every character outside A-Za-z0-9-_ (AC-25f)", () => {
  assert.equal(downloadName("Sector weights 2026", "svg"), "Sector_weights_2026.svg");
  assert.equal(downloadName("a-b_c.ü/x", "csv"), "a-b_c___x.csv");
});

test("downloads: note as Markdown, flow and diagram as Mermaid, chart as its light SVG (AC-25f, AC-25g, AC-63)", () => {
  assert.deepEqual(download(block({ kind: "note", title: "N", source: "Because **x**" })), { name: "N.md", type: "text/markdown", text: "Because **x**" });
  assert.equal(download(block({ kind: "flow", title: "F", source: FLOW_F }))?.text, FLOW_F);
  assert.equal(download(block({ kind: "flow", title: "F", source: FLOW_F }))?.name, "F.mmd");
  assert.equal(download(block({ kind: "diagram", title: "M", source: MIND_M }))?.text, MIND_M);
  const chart = block({ kind: "chart", title: "Sector weights 2026", rendered: { light: "<svg light/>", dark: "<svg dark/>" } });
  assert.deepEqual(download(chart), { name: "Sector_weights_2026.svg", type: "image/svg+xml", text: "<svg light/>" });
  assert.equal(download(block({ kind: "chart", rendered: null, live: true, live_error: "x" })), null);
});

test("a table downloads as CSV, a live one with its resolved rows (AC-25c, AC-61)", () => {
  const t = block({ kind: "table", title: "T", source: { columns: ["a", "b"], rows: [[1, null], ["x, y", 2.5]] } });
  assert.equal(download(t)?.text, 'a,b\n1,\n"x, y",2.5');
  const live = block({
    kind: "table", title: "W", live: true, source: { live: "/steps/0/result/weights", columns: ["sector", "weight"] },
    rendered: { rows: [["Energy", 0.125], ["Utilities", 0.31]] },
  });
  assert.deepEqual(download(live), { name: "W.csv", type: "text/csv", text: "sector,weight\nEnergy,0.125\nUtilities,0.31" });
});

test("tiles download raw numbers and checklists as task lines (AC-63)", () => {
  const tiles = block({
    kind: "tiles", title: "T",
    source: { tiles: [{ label: "Utilities", value: 0.31, format: "percent", change: 0.04, note: "vs Q2" }, { label: "Issuers", value: 1234.5, change: -12 }] },
    rendered: { values: [0.31, 1234.5] },
  });
  assert.equal(download(tiles)?.text, "label,value,change,note\nUtilities,0.31,0.04,vs Q2\nIssuers,1234.5,-12,");
  const nullTile = block({ kind: "tiles", title: "T", source: { tiles: [{ label: "x", value: { live: "/a" } }] }, rendered: { values: [null] } });
  assert.equal(download(nullTile)?.text, "label,value,change,note\nx,,,");
  const list = block({ kind: "checklist", title: "C", source: { items: [{ text: "a", done: true }, { text: "b", done: false }] } });
  assert.deepEqual(download(list), { name: "C.md", type: "text/markdown", text: "- [x] a\n- [ ] b" });
});

test("tile values: grouped thousands with at most 2 decimals, percent with one decimal, null as a dash (AC-50)", () => {
  assert.equal(tileValue(0.31, "percent"), "31.0%");
  assert.equal(tileValue(1234.5), "1,234.5");
  assert.equal(tileValue(1234.5678, "number"), "1,234.57");
  assert.equal(tileValue(null), "—");
  assert.equal(tileChange(0.04, "percent"), "+4.0 pts");
  assert.equal(tileChange(-0.04, "percent"), "-4.0 pts");
  assert.equal(tileChange(-12), "-12");
  assert.equal(tileChange(1500), "+1,500");
  assert.equal(tileChange(0), "0");
});

test("Edit shows a table as CSV, a live table, tiles and a chart as JSON, text sources as text (AC-25h, AC-63)", () => {
  assert.equal(editText(block({ kind: "note", source: "Why" })), "Why");
  assert.equal(editText(block({ kind: "table", source: { columns: ["a", "b"], rows: [[1, 2]] } })), "a,b\n1,2");
  const live = { live: "/x", columns: ["a"] };
  assert.equal(editText(block({ kind: "table", source: live })), JSON.stringify(live, null, 2));
  const tiles = { tiles: [{ label: "a", value: 1 }] };
  assert.equal(editText(block({ kind: "tiles", source: tiles })), JSON.stringify(tiles, null, 2));
});

test("a saved table CSV keeps numbers, nulls and text the way the spec reads them (AC-25h)", () => {
  assert.deepEqual(csvToTable("a,b\n1,\nx,2.5"), { columns: ["a", "b"], rows: [[1, null], ["x", 2.5]] });
  assert.deepEqual(csvToTable("a\n1e3\n-4\n 7 \nnan\ninf\n\"q,\"\"r\"\"\""), { columns: ["a"], rows: [[1000], [-4], [7], ["nan"], ["inf"], ['q,"r"']] });
  assert.deepEqual(csvToTable("a,b\r\n1,2\r\n"), { columns: ["a", "b"], rows: [[1, 2]] });
  assert.equal(toCsv(["a"], [["multi\nline"]]), 'a\n"multi\nline"');
});

test("an edit sends text, a table read from CSV, or parsed JSON; bad JSON stays local", () => {
  assert.deepEqual(editedSource(block({ kind: "note", source: "a" }), "b"), { source: "b" });
  assert.deepEqual(editedSource(block({ kind: "table", source: { columns: ["a"], rows: [] } }), "a\n1"), { source: { columns: ["a"], rows: [[1]] } });
  assert.deepEqual(editedSource(block({ kind: "chart", source: { mark: "bar" } }), '{"mark": "line"}'), { source: { mark: "line" } });
  assert.ok("error" in editedSource(block({ kind: "chart", source: { mark: "bar" } }), "{"));
});

test("a refusal shows its detail without the status in front (AC-25h)", () => {
  assert.equal(detailOf(new Error("422: row 2 has 1 cells, expected 2")), "row 2 has 1 cells, expected 2");
  assert.equal(detailOf(new Error("Failed to fetch")), "Failed to fetch");
});

test("the 10 s poll redraws while the plan runs and once after it stops (AC-57, AC-64)", () => {
  assert.equal(boardNeedsReload("running", "running"), true);
  assert.equal(boardNeedsReload("running", "done"), true);
  assert.equal(boardNeedsReload("done", "done"), false);
  assert.equal(boardNeedsReload("approved", "running"), true);
  assert.equal(boardNeedsReload(null, "draft"), false);
});

test("a chart is a base64 data: URL of its SVG, any character kept (AC-22)", () => {
  const url = svgDataUrl("<svg>Büro ✓</svg>");
  assert.ok(url.startsWith("data:image/svg+xml;base64,"));
  assert.equal(new TextDecoder().decode(Uint8Array.from(atob(url.split(",")[1]), (c) => c.charCodeAt(0))), "<svg>Büro ✓</svg>");
});

test("notes: Markdown subset, raw HTML as text, only http(s) links (AC-24)", () => {
  const md = parseMarkdown("# Head\n\nBecause **x** and *y*, `z`\n\n- one\n- two\n\n1. first");
  assert.deepEqual(md.map((b) => b.t), ["h", "p", "ul", "ol"]);
  assert.deepEqual(parseInline("**x**"), [{ t: "b", children: [{ t: "text", text: "x" }] }]);
  assert.deepEqual(parseInline("<img src=x onerror=\"document.title='hit'\">"), [{ t: "text", text: "<img src=x onerror=\"document.title='hit'\">" }]);
  assert.deepEqual(parseInline("[a](javascript:alert(1))"), [{ t: "text", text: "[a](javascript:alert(1))" }]);
  assert.deepEqual(parseInline("[ARP](https://example.com/x)"), [{ t: "link", href: "https://example.com/x", children: [{ t: "text", text: "ARP" }] }]);
  assert.deepEqual(parseInline("[f](file:///etc/passwd)")[0].t, "text");
});

test("flowchart groups keep source order, skip emphasis, at most 4; other types have none (AC-47)", () => {
  assert.deepEqual(diagramGroups(GROUPED_G), ["Housing", "Berlin", "Munich"]);
  assert.deepEqual(diagramGroups(MIND_M), []);
  assert.equal(hasEmphasis(GROUPED_G), true);
  assert.equal(hasEmphasis(FLOW_F), false);
  assert.equal(diagramType("%% c\n\nsequenceDiagram\n  A->>B: x"), "sequenceDiagram");
  assert.equal(groupLabel("DataTeam"), "Data Team");
  assert.equal(groupLabel("Housing"), "Housing");
  assert.deepEqual([...GROUP_SLOTS], ["--cat-1", "--cat-4", "--cat-2", "--muted"]);
});

const THEME: DiagramTheme = {
  dark: false, font: "Geist", panel: "#ffffff", text: "#121722", muted: "#4f5a6b", line: "#7b8696", hair: "#d8dee7", well: "#eaeef3",
  groups: [
    { fill: "#e1ecfa", stroke: "#2a78d6", text: "#1f4f8e" }, { fill: "#e9e6fa", stroke: "#6250d6", text: "#433a90" },
    { fill: "#f7e4ee", stroke: "#c2407f", text: "#802e57" }, { fill: "#e5e7ea", stroke: "#4f5a6b", text: "#353d4a" },
  ],
};

test("the frame draws with ARP's group colours and no classDef or config from the source", () => {
  const src = "%%{init: {\"theme\": \"dark\"}}%%\nflowchart LR\n  classDef Ops fill:#f00\n  a:::Ops --> b; classDef x color:red\n  class b emphasis";
  const out = themedSource(src, THEME);
  assert.ok(!out.includes("%%{"));
  assert.ok(!out.includes("#f00") && !out.includes("color:red"));
  assert.ok(out.includes("classDef Ops fill:#e1ecfa,stroke:#2a78d6,color:#1f4f8e,stroke-width:1.5px"));
  assert.ok(out.includes("classDef emphasis stroke-width:3px,font-weight:600"));
  assert.ok(themedSource("---\nconfig:\n  theme: dark\n---\nflowchart LR\n  a --> b", THEME).startsWith("flowchart LR"));
  assert.equal(themedSource(MIND_M, THEME), MIND_M);
  assert.equal(firstLine("\nParse error on line 2:\n...a -->\n"), "Parse error on line 2:");
});

const read = (rel: string) => {
  const up = ["../", "../../"].map((p) => new URL(`${p}${rel}`, import.meta.url));
  return readFileSync(up.find((u) => existsSync(u)) ?? up[0], "utf8");
};

test("board-diagram.html opens with the frame's Content-Security-Policy and loads a plain .ts entry (AC-55b)", () => {
  const html = read("board-diagram.html");
  const head = html.slice(html.indexOf("<head>") + 6).trimStart();
  assert.ok(head.startsWith(`<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src data:" />`));
  assert.ok(html.includes('src="/src/boardDiagram.ts"'));
  const entry = read("src/boardDiagram.ts");
  assert.ok(!/from "react"|from "react-dom"/.test(entry));
  assert.ok(entry.includes('import("mermaid")') && entry.includes('import("@mermaid-js/layout-elk")'));
  assert.ok(entry.includes("if (e.source !== window.parent) return;"));
});

test("the Board's frame is sandboxed to scripts only (signin-headers-containers AC-34, supersedes AC-49d)", () => {
  const board = read("src/components/AgentBoard.tsx");
  assert.ok(board.includes('sandbox="allow-scripts"'));
  assert.ok(board.includes("e.source !== frame.current.contentWindow"));
});

test("DESIGN.md names the diagram group colours (agent-board slice 3)", () => {
  const design = read("../DESIGN.md");
  const para = design.split("\n").find((l) => l.startsWith("**Chart Colours.**")) ?? "";
  assert.ok(para.includes("`--cat-1`, `--cat-4`, `--cat-2`, then `--muted`"), para);
});

test("a diagram keeps its natural width when it fits, else shrinks no further than 11 px text and scrolls", () => {
  assert.equal(diagramWidth(200, 294), 200);
  assert.equal(diagramWidth(350, 294), 294);
  assert.equal(diagramWidth(1000, 294), Math.ceil(1000 * MIN_DIAGRAM_SCALE));
  assert.ok(14 * (diagramWidth(1000, 294) / 1000) >= 11);
});

test("underscores inside words stay text in notes", () => {
  assert.deepEqual(parseInline("sector_weight_total"), [{ t: "text", text: "sector_weight_total" }]);
  assert.deepEqual(parseInline("set_a__b__c"), [{ t: "text", text: "set_a__b__c" }]);
  assert.deepEqual(parseInline("an _aside_ here")[1], { t: "i", children: [{ t: "text", text: "aside" }] });
  assert.deepEqual(parseInline("__bold__ start")[0], { t: "b", children: [{ t: "text", text: "bold" }] });
});
