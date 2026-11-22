// The Board tab of the Agent screen (docs/superpowers/specs/2026-11-22-agent-board.md, slice 3). Plain functions,
// no React: the diagram frame (src/boardDiagram.ts) imports the diagram helpers too.

export type BlockKind = "note" | "table" | "chart" | "flow" | "diagram" | "tiles" | "checklist";
export type Cell = string | number | null;
export interface Tile { label: string; value: number | { live: string }; format?: "number" | "percent"; change?: number; note?: string }
export interface ChecklistItem { text: string; done: boolean }

export interface BoardBlock {
  id: string;
  kind: BlockKind;
  title: string;
  source: unknown;
  position: number;
  version: number;
  origin: "person" | "agent";
  unverified: number[];
  rendered: any; // its shape depends on `kind` (spec "Rendering")
  live?: boolean;
  live_error?: string | null;
  live_step?: number | null;
}
export interface Board { thread_kind: string; thread_id: string; blocks: BoardBlock[] }

export const EMPTY_BOARD = "Nothing on the board yet. Ask for a chart, diagram, table or checklist.";
export const DRAW_PLACEHOLDER = "Ask the agent to draw something…";
export const BOARD_POLL_MS = 10_000;
export const UNDO_BAR_MS = 5_000;

/** `Not in ARP data: …`: the first 10 numbers, then ` and <k> more` (D4). */
export function unverifiedLine(nums: number[]): string | null {
  if (nums.length === 0) return null;
  const shown = nums.slice(0, 10).map(String).join(", ");
  return `Not in ARP data: ${shown}${nums.length > 10 ? ` and ${nums.length - 10} more` : ""}`;
}

/** `Live · step <n>`, or `Live` when the pointer names no step. */
export function liveLabel(b: Pick<BoardBlock, "live" | "live_step">): string | null {
  if (!b.live) return null;
  return b.live_step == null ? "Live" : `Live · step ${b.live_step}`;
}

export type MenuItem = "Edit" | "Change with agent…" | "Move up" | "Move down" | "Undo last change" | "Download" | "Delete";

/** The `⋯` menu: `Move up` not on the first block, `Move down` not on the last, `Undo last change` not at version 1. */
export function menuItems(index: number, count: number, version: number): MenuItem[] {
  const items: MenuItem[] = ["Edit", "Change with agent…"];
  if (index > 0) items.push("Move up");
  if (index < count - 1) items.push("Move down");
  if (version > 1) items.push("Undo last change");
  items.push("Download", "Delete");
  return items;
}

/** A download's file name: the title with every character outside `A-Za-z0-9-_` replaced by `_`. */
export const downloadName = (title: string, ext: string): string => `${title.replace(/[^A-Za-z0-9\-_]/g, "_")}.${ext}`;

function csvField(v: Cell): string {
  if (v === null) return "";
  const s = String(v);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** CSV with a header row; `null` is an empty cell. */
export const toCsv = (columns: string[], rows: Cell[][]): string => [columns, ...rows].map((r) => r.map(csvField).join(",")).join("\n");

/** RFC 4180 records: quoted fields may hold `,`, `""` and line breaks. A trailing line break adds no record. */
export function parseCsvRecords(text: string): string[][] {
  const out: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (ch === '"') quoted = false;
      else field += ch;
    } else if (ch === '"' && field === "") quoted = true;
    else if (ch === ",") { row.push(field); field = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      out.push(row);
      row = [];
      field = "";
    } else field += ch;
  }
  if (field !== "" || row.length > 0) {
    row.push(field);
    out.push(row);
  }
  return out;
}

const NUMBER = /^[+-]?(\d(_?\d)*(\.(\d(_?\d)*)?)?|\.\d(_?\d)*)([eE][+-]?\d(_?\d)*)?$/;

/** A saved CSV cell: a number when Python's `float()` reads it as finite (an int without `.`, `e` or `E`), `null`
 * when empty, else the text (spec "On screen", `table`). */
export function csvCell(raw: string): Cell {
  if (raw === "") return null;
  const t = raw.trim();
  if (NUMBER.test(t)) {
    const n = Number(t.replace(/_/g, ""));
    if (Number.isFinite(n)) return /[.eE]/.test(t) ? n : Math.trunc(n);
  }
  return raw;
}

/** A table's CSV, read back as its source: the first record is `columns`. */
export function csvToTable(text: string): { columns: string[]; rows: Cell[][] } {
  const [columns = [], ...rows] = parseCsvRecords(text);
  return { columns, rows: rows.map((r) => r.map(csvCell)) };
}

const pretty = (v: unknown) => JSON.stringify(v, null, 2);

/** What `Edit` shows: notes, flows and diagrams as text, a table that holds rows as CSV, anything else as JSON. */
export function editText(b: Pick<BoardBlock, "kind" | "source">): string {
  if (typeof b.source === "string") return b.source;
  if (b.kind === "table" && isRowsTable(b.source)) return toCsv(b.source.columns, b.source.rows);
  return pretty(b.source);
}

const isRowsTable = (s: unknown): s is { columns: string[]; rows: Cell[][] } =>
  typeof s === "object" && s !== null && Array.isArray((s as { rows?: unknown }).rows) && !("live" in s);

/** The source a saved edit sends, or the reason it cannot be read. */
export function editedSource(b: Pick<BoardBlock, "kind" | "source">, text: string): { source: unknown } | { error: string } {
  if (typeof b.source === "string") return { source: text };
  if (b.kind === "table" && isRowsTable(b.source)) return { source: csvToTable(text) };
  try {
    return { source: JSON.parse(text) };
  } catch (e) {
    return { error: `This is not valid JSON: ${(e as Error).message}` };
  }
}

const grouped = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 2 });
const percent = (n: number) => (n * 100).toFixed(1);

/** A tile's value: `1,234.5` (at most 2 decimals), or for `percent` × 100 with one decimal and `%`; `null` is `—`. */
export function tileValue(v: number | null, format?: Tile["format"]): string {
  if (v === null) return "—";
  return format === "percent" ? `${percent(v)}%` : grouped(v);
}

/** A tile's change: `+` above 0, `-` below, no sign at 0; for `percent` × 100 with one decimal and ` pts`. */
export function tileChange(c: number, format?: Tile["format"]): string {
  const sign = c > 0 ? "+" : c < 0 ? "-" : "";
  const abs = Math.abs(c);
  return format === "percent" ? `${sign}${percent(abs)} pts` : `${sign}${grouped(abs)}`;
}

/** The download of a block, or null when there is nothing to save (a chart that did not draw). */
export function download(b: BoardBlock): { name: string; type: string; text: string } | null {
  const file = (ext: string, type: string, text: string) => ({ name: downloadName(b.title, ext), type, text });
  const s = b.source as Record<string, unknown>;
  switch (b.kind) {
    case "note":
      return file("md", "text/markdown", b.source as string);
    case "flow":
    case "diagram":
      return file("mmd", "text/plain", b.source as string);
    case "chart":
      return b.rendered?.light ? file("svg", "image/svg+xml", b.rendered.light) : null;
    case "table": {
      const rows = (b.live ? b.rendered?.rows : s.rows) as Cell[][] | undefined;
      return file("csv", "text/csv", toCsv(s.columns as string[], rows ?? []));
    }
    case "tiles": {
      const tiles = s.tiles as Tile[];
      const values = (b.rendered?.values ?? []) as (number | null)[];
      const rows = tiles.map((t, i) => [t.label, num(values[i] ?? null), num(t.change ?? null), t.note ?? null]);
      return file("csv", "text/csv", toCsv(["label", "value", "change", "note"], rows));
    }
    case "checklist":
      return file("md", "text/markdown", (s.items as ChecklistItem[]).map((it) => `- [${it.done ? "x" : " "}] ${it.text}`).join("\n"));
  }
}

const num = (v: number | null): Cell => (v === null ? null : JSON.stringify(v));

/** A data: URL of an SVG, base64 so any character survives (D1: a chart is shown as an image). */
export function svgDataUrl(svg: string): string {
  const bytes = new TextEncoder().encode(svg);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return `data:image/svg+xml;base64,${btoa(bin)}`;
}

/** The detail of a failed request, without the status the API client puts in front (`422: …`). */
export const detailOf = (e: unknown): string => String((e as Error)?.message ?? e).replace(/^\d{3}: /, "");

/** Whether a 10 s poll should redraw the board: while the plan runs, and once on the first status after it ran. */
export const boardNeedsReload = (prev: string | null, status: string): boolean => status === "running" || prev === "running";

// --- Markdown subset (spec "On screen", `note`): headings, bold, italics, lists, inline code, http(s) links. ---

export type Inline =
  | { t: "text"; text: string }
  | { t: "code"; text: string }
  | { t: "b"; children: Inline[] }
  | { t: "i"; children: Inline[] }
  | { t: "link"; href: string; children: Inline[] };
export type MdBlock =
  | { t: "h"; level: 1 | 2 | 3 | 4 | 5 | 6; children: Inline[] }
  | { t: "p"; children: Inline[] }
  | { t: "ul" | "ol"; items: Inline[][] };

const INLINE = /`([^`]+)`|\*\*(.+?)\*\*|__(.+?)__|\*([^*\s](?:[^*]*[^*\s])?)\*|_([^_\s](?:[^_]*[^_\s])?)_|\[([^\]]+)\]\(([^)\s]+)\)/;

/** Inline Markdown. Raw HTML stays text; a link whose target is not `http://` or `https://` stays as written. */
export function parseInline(src: string): Inline[] {
  const out: Inline[] = [];
  let rest = src;
  const text = (s: string) => {
    if (!s) return;
    const last = out.at(-1);
    if (last?.t === "text") last.text += s;
    else out.push({ t: "text", text: s });
  };
  while (rest) {
    const m = INLINE.exec(rest);
    if (!m) { text(rest); break; }
    text(rest.slice(0, m.index));
    if (m[1] !== undefined) out.push({ t: "code", text: m[1] });
    else if (m[2] !== undefined || m[3] !== undefined) out.push({ t: "b", children: parseInline(m[2] ?? m[3]) });
    else if (m[4] !== undefined || m[5] !== undefined) out.push({ t: "i", children: parseInline(m[4] ?? m[5]) });
    else if (/^https?:\/\//i.test(m[7])) out.push({ t: "link", href: m[7], children: parseInline(m[6]) });
    else text(m[0]);
    rest = rest.slice(m.index + m[0].length);
  }
  return out;
}

/** Markdown blocks: `#` headings, `-`/`*`/`+` and `1.` lists, paragraphs split at blank lines. */
export function parseMarkdown(src: string): MdBlock[] {
  const out: MdBlock[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) out.push({ t: "p", children: parseInline(para.join("\n")) });
    para = [];
  };
  for (const line of src.split(/\r\n|\r|\n/)) {
    const h = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
    const li = /^\s*(?:([-*+])|(\d+)[.)])\s+(.*)$/.exec(line);
    if (!line.trim()) flush();
    else if (h) {
      flush();
      out.push({ t: "h", level: h[1].length as 1, children: parseInline(h[2]) });
    } else if (li) {
      flush();
      const kind = li[1] ? "ul" : "ol";
      const last = out.at(-1);
      if (last && last.t === kind) last.items.push(parseInline(li[3]));
      else out.push({ t: kind, items: [parseInline(li[3])] });
    } else para.push(line);
  }
  flush();
  return out;
}

// --- Diagrams (spec Phase 2 "On screen (slice 3)") ---

/** The first word of a diagram's first line that is not empty and not a `%%` line. */
export function diagramType(source: string): string {
  const line = source.split(/\r\n|\r|\n/).find((l) => l.trim() && !l.trim().startsWith("%%"));
  return line?.trim().split(/\s+/)[0] ?? "";
}
const isFlowchart = (source: string) => /^(flowchart|graph)$/.test(diagramType(source));

/** A flowchart's colour groups: each `:::Name` other than `emphasis`, in the order they first appear, at most 4. */
export function diagramGroups(source: string): string[] {
  if (!isFlowchart(source)) return [];
  const names = [...source.matchAll(/:::([A-Za-z][A-Za-z0-9_]*)/g)].map((m) => m[1]).filter((n) => n !== "emphasis");
  return [...new Set(names)].slice(0, 4);
}

/** Whether a flowchart marks a key step (`class <id> emphasis` or `:::emphasis`). */
export const hasEmphasis = (source: string): boolean =>
  isFlowchart(source) && (/(^|[\n\r;}])[^\S\r\n]*class\s+\S+\s+emphasis\s*($|[\n\r;])/i.test(source) || /:::emphasis\b/.test(source));

/** `DataTeam` → `Data Team`. */
export const groupLabel = (name: string): string => name.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/([A-Z])([A-Z][a-z])/g, "$1 $2").replace(/_/g, " ");

/** The group hues in order (`--cat-3` gold and amber are never group colours). */
export const GROUP_SLOTS = ["--cat-1", "--cat-4", "--cat-2", "--muted"] as const;

export interface GroupColours { fill: string; stroke: string; text: string }
export interface DiagramTheme {
  dark: boolean;
  font: string;
  panel: string;
  text: string;
  muted: string;
  line: string;
  hair: string;
  well: string;
  groups: GroupColours[]; // one per GROUP_SLOTS entry
}

/** What the Board posts to a diagram frame, and what the frame answers. */
export type ToFrame = { type: "draw"; source: string; theme: DiagramTheme };
export type FromFrame = { type: "drawn"; height: number } | { type: "error"; message: string };

/** The source Mermaid draws: no config and no `classDef` of its own (front matter, `%%{…}%%` and `classDef`
 * statements dropped), then ARP's group colours and the `emphasis` style. */
export function themedSource(source: string, theme: DiagramTheme): string {
  let s = source.replace(/^\s*---[\s\S]*?\n\s*---\s*(\r\n|\r|\n)/, "").replace(/%%\{[\s\S]*?\}%%/g, "");
  s = s
    .split(/\r\n|\r|\n/)
    .map((line) => line.split(";").filter((st) => !/^\s*(end\s+)*classDef(\s|$)/i.test(st)).join(";"))
    .join("\n");
  if (!isFlowchart(source)) return s;
  const defs = diagramGroups(source).map((g, i) => {
    const c = theme.groups[i];
    return `classDef ${g} fill:${c.fill},stroke:${c.stroke},color:${c.text},stroke-width:1.5px`;
  });
  defs.push("classDef emphasis stroke-width:3px,font-weight:600");
  return `${s}\n${defs.join("\n")}`;
}

/** The first line of an error, for `This diagram could not be drawn: …`. */
export const firstLine = (message: string): string => message.split(/\r\n|\r|\n/).find((l) => l.trim())?.trim() ?? message;
