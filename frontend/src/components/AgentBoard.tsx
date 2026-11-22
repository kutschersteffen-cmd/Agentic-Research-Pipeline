import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { api } from "../api/client";
import {
  BOARD_POLL_MS, DRAW_PLACEHOLDER, EMPTY_BOARD, GROUP_SLOTS, UNDO_BAR_MS, boardNeedsReload, detailOf, diagramGroups, download, editText,
  editedSource, firstLine, groupLabel, hasEmphasis, liveLabel, menuItems, parseMarkdown, svgDataUrl, tileChange, tileValue, unverifiedLine,
  type BoardBlock, type Cell, type ChecklistItem, type DiagramTheme, type FromFrame, type Inline, type MenuItem, type Tile, type ToFrame,
} from "../lib/board";

/** The Board tab (spec agent-board, slice 3): a plan's blocks top to bottom, a `⋯` menu on each, and one field at the
 * bottom that asks the agent to draw. While the tab is open it re-reads the plan every 10 s and redraws the blocks
 * while the plan runs (D9). */
export function AgentBoard({ planId, planStatus, idPrefix }: { planId: string; planStatus: string; idPrefix: string }) {
  const [blocks, setBlocks] = useState<BoardBlock[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [drawing, setDrawing] = useState(false);
  const [drawError, setDrawError] = useState<string | null>(null);
  const [deleted, setDeleted] = useState<BoardBlock | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);
  const theme = useDiagramTheme();
  const field = useRef<HTMLInputElement>(null);

  const load = useCallback(
    () => api.getBoard(planId).then((b) => setBlocks(b.blocks)).catch((e) => setError(`The board could not be loaded: ${detailOf(e)}.`)),
    [planId],
  );
  useEffect(() => { void load(); }, [load]);

  // Every 10 s: the plan's status; the blocks too while it runs, and once more on the first status after it ran.
  const status = useRef(planStatus);
  useEffect(() => {
    const t = setInterval(() => {
      api.getPlan(planId).then((p) => {
        if (boardNeedsReload(status.current, p.status)) void load();
        status.current = p.status;
      }).catch(() => {});
    }, BOARD_POLL_MS);
    return () => clearInterval(t);
  }, [planId, load]);

  // The `Block deleted · Undo` bar stays 5 s.
  useEffect(() => {
    if (!deleted) return;
    const t = setTimeout(() => setDeleted(null), UNDO_BAR_MS);
    return () => clearTimeout(t);
  }, [deleted]);

  /** A change, then the board read again; a refusal shows above the blocks. */
  async function change(fn: () => Promise<unknown>): Promise<boolean> {
    setError(null);
    try {
      await fn();
      return true;
    } catch (e) {
      setError(detailOf(e));
      return false;
    } finally {
      void load();
    }
  }

  async function draw() {
    const p = prompt.trim();
    if (!p || drawing) return;
    setDrawing(true);
    setDrawError(null);
    try {
      await api.drawBlock(planId, p);
      setPrompt("");
      await load();
    } catch (e) {
      setDrawError(detailOf(e));
    } finally {
      setDrawing(false);
      requestAnimationFrame(() => field.current?.focus());
    }
  }

  function remove(b: BoardBlock) {
    setBlocks((xs) => xs?.filter((x) => x.id !== b.id) ?? null);
    void change(() => api.deleteBlock(planId, b.id)).then((ok) => ok && setDeleted(b));
  }
  function restore(b: BoardBlock) {
    setDeleted(null);
    void change(() => api.addBlock(planId, { kind: b.kind, title: b.title, source: b.source, origin: b.origin, unverified: b.unverified, position: b.position }));
  }
  const move = (b: BoardBlock, position: number) => change(() => api.patchBlock(planId, b.id, { position }));
  /** A tick shows at once; the board read after the PATCH confirms it. */
  function tick(b: BoardBlock, items: ChecklistItem[]) {
    setBlocks((xs) => xs?.map((x) => (x.id === b.id ? { ...x, source: { items } } : x)) ?? null);
    void change(() => api.patchBlock(planId, b.id, { source: { items } }));
  }

  const list = blocks ?? [];
  return (
    <div className="board">
      {error && <p className="error-text" role="alert">{error}</p>}
      {blocks === null ? (
        <p className="muted">Loading the board…</p>
      ) : list.length === 0 && !drawing ? (
        <p className="muted board-empty">{EMPTY_BOARD}</p>
      ) : (
        <ol className="board-blocks" aria-label="Board">
          {list.map((b, i) => (
            <BlockCard key={b.id} block={b} index={i} count={list.length} planId={planId} theme={theme} idPrefix={idPrefix}
              dragging={dragId === b.id} onDragStart={() => setDragId(b.id)} onDragEnd={() => setDragId(null)}
              onDrop={() => {
                const from = list.find((x) => x.id === dragId);
                setDragId(null);
                if (from && from.id !== b.id) void move(from, i);
              }}
              change={change} onMove={(to) => move(b, to)} onDelete={() => remove(b)} onTick={(items) => tick(b, items)} />
          ))}
          {drawing && (
            <li className="board-block board-drawing" role="status">
              <p className="muted">Drawing…</p>
            </li>
          )}
        </ol>
      )}
      {deleted && (
        <div className="board-undo" role="status">
          <span>Block deleted</span>
          <span aria-hidden="true">·</span>
          <button type="button" className="link-button" onClick={() => restore(deleted)}>Undo</button>
        </div>
      )}
      <form className="board-ask" onSubmit={(e) => { e.preventDefault(); void draw(); }}>
        <label className="visually-hidden" htmlFor={`${idPrefix}-board-ask`}>Ask the agent to draw</label>
        <input id={`${idPrefix}-board-ask`} ref={field} type="text" value={prompt} disabled={drawing} maxLength={2000}
          placeholder={DRAW_PLACEHOLDER} onChange={(e) => setPrompt(e.target.value)}
          aria-describedby={drawError ? `${idPrefix}-board-ask-err` : undefined} />
        {drawError && <p id={`${idPrefix}-board-ask-err`} className="error-text board-field-error">{drawError}</p>}
      </form>
    </div>
  );
}

function BlockCard(p: {
  block: BoardBlock; index: number; count: number; planId: string; theme: DiagramTheme | null; idPrefix: string; dragging: boolean;
  onDragStart: () => void; onDragEnd: () => void; onDrop: () => void;
  change: (fn: () => Promise<unknown>) => Promise<boolean>; onMove: (to: number) => void; onDelete: () => void;
  onTick: (items: ChecklistItem[]) => void;
}) {
  const { block: b, planId } = p;
  const [editing, setEditing] = useState<string | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [asking, setAsking] = useState<string | null>(null);
  const [askBusy, setAskBusy] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const base = `${p.idPrefix}-b-${b.id}`;
  const live = liveLabel(b);
  const unverified = unverifiedLine(b.unverified);

  async function save() {
    const out = editedSource(b, editing ?? "");
    if ("error" in out) return setEditError(out.error);
    setEditError(null);
    try {
      await api.patchBlock(planId, b.id, { source: out.source });
      setEditing(null);
    } catch (e) {
      return setEditError(detailOf(e));
    }
    await p.change(async () => {}); // read the board again
  }
  async function askAgent() {
    const text = asking?.trim();
    if (!text || askBusy) return;
    setAskBusy(true);
    setAskError(null);
    try {
      await api.drawBlock(planId, text, b.id);
      setAsking(null);
      await p.change(async () => {});
    } catch (e) {
      setAskError(detailOf(e));
    } finally {
      setAskBusy(false);
    }
  }
  function pick(item: MenuItem) {
    if (item === "Edit") { setEditing(editText(b)); setEditError(null); }
    else if (item === "Change with agent…") { setAsking(""); setAskError(null); }
    else if (item === "Move up") p.onMove(p.index - 1);
    else if (item === "Move down") p.onMove(p.index + 1);
    else if (item === "Undo last change") void p.change(() => api.undoBlock(planId, b.id));
    else if (item === "Download") save_(b);
    else if (item === "Delete") p.onDelete();
  }

  return (
    <li className={`board-block${p.dragging ? " board-dragging" : ""}${over ? " board-drop" : ""}`} aria-labelledby={`${base}-h`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); p.onDrop(); }}>
      <div className="board-block-head">
        <h3 id={`${base}-h`} className="board-title" draggable onDragStart={(e) => { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", b.id); p.onDragStart(); }} onDragEnd={p.onDragEnd}>
          {b.title}
        </h3>
        {b.origin === "agent" && <span className="board-label">Agent</span>}
        {live && <span className="board-label board-label-live">{live}</span>}
        <BlockMenu id={`${base}-menu`} title={b.title} items={menuItems(p.index, p.count, b.version)} onPick={pick} />
      </div>
      {editing !== null ? (
        <form className="board-edit" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <label className="visually-hidden" htmlFor={`${base}-edit`}>Source of {b.title}</label>
          <textarea id={`${base}-edit`} className="mono" value={editing} rows={Math.min(16, editing.split("\n").length + 1)} autoFocus
            onChange={(e) => setEditing(e.target.value)} aria-describedby={editError ? `${base}-edit-err` : undefined} />
          {editError && <p id={`${base}-edit-err`} className="error-text board-field-error">{editError}</p>}
          <div className="toolbar">
            <button type="submit">Save</button>
            <button type="button" className="secondary" onClick={() => { setEditing(null); setEditError(null); }}>Cancel</button>
          </div>
        </form>
      ) : (
        <BlockContent block={b} theme={p.theme} onTick={p.onTick} />
      )}
      {unverified && <p className="board-note-line">{unverified}</p>}
      {b.live_error && <p className="board-note-line">{b.live_error}</p>}
      {asking !== null && (
        <form className="board-ask board-ask-block" onSubmit={(e) => { e.preventDefault(); void askAgent(); }}>
          <label className="visually-hidden" htmlFor={`${base}-ask`}>Change {b.title} with the agent</label>
          <input id={`${base}-ask`} type="text" value={asking} disabled={askBusy} maxLength={2000} autoFocus
            placeholder="Say what to change…" onChange={(e) => setAsking(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Escape") setAsking(null); }} aria-describedby={askError ? `${base}-ask-err` : undefined} />
          {askBusy && <p className="muted board-field-error" role="status">Drawing…</p>}
          {askError && <p id={`${base}-ask-err`} className="error-text board-field-error">{askError}</p>}
        </form>
      )}
    </li>
  );
}

function save_(b: BoardBlock) {
  const file = download(b);
  if (!file) return;
  const href = URL.createObjectURL(new Blob([file.text], { type: file.type }));
  const a = document.createElement("a");
  a.href = href;
  a.download = file.name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

/** The `⋯` menu: a button and a list of actions; Escape or a click elsewhere closes it. */
function BlockMenu({ id, title, items, onPick }: { id: string; title: string; items: MenuItem[]; onPick: (i: MenuItem) => void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    box.current?.querySelector<HTMLButtonElement>("[role=menuitem]")?.focus();
    const away = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);
  function onKeyDown(e: KeyboardEvent) {
    const all = [...(box.current?.querySelectorAll<HTMLButtonElement>("[role=menuitem]") ?? [])];
    const at = all.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "Escape") { e.preventDefault(); setOpen(false); button.current?.focus(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); all[(at + 1) % all.length]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); all[(at - 1 + all.length) % all.length]?.focus(); }
  }
  return (
    <div className="board-menu" ref={box} onKeyDown={onKeyDown}>
      <button ref={button} type="button" className="board-menu-button" aria-haspopup="menu" aria-expanded={open}
        aria-controls={open ? id : undefined} aria-label={`Actions for ${title}`} onClick={() => setOpen((o) => !o)}>⋯</button>
      {open && (
        <ul id={id} role="menu" className="board-menu-list" aria-label={`Actions for ${title}`}>
          {items.map((i) => (
            <li key={i} role="none">
              <button type="button" role="menuitem" className={i === "Delete" ? "danger-text" : undefined}
                onClick={() => { setOpen(false); button.current?.focus(); onPick(i); }}>{i}</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function BlockContent({ block: b, theme, onTick }: { block: BoardBlock; theme: DiagramTheme | null; onTick: (items: ChecklistItem[]) => void }) {
  const s = b.source as Record<string, unknown>;
  switch (b.kind) {
    case "note":
      return <div className="board-note">{markdown(b.source as string)}</div>;
    case "table": {
      const rows = ((b.live ? b.rendered?.rows : s.rows) ?? []) as Cell[][];
      return <BoardTable columns={s.columns as string[]} rows={rows} />;
    }
    case "chart": {
      const svg = theme && b.rendered ? (theme.dark ? b.rendered.dark : b.rendered.light) : null;
      if (svg) return <img className="board-chart" src={svgDataUrl(svg)} alt={b.title} />;
      return b.live_error ? null : <p className="muted">This chart could not be drawn.</p>;
    }
    case "flow":
    case "diagram":
      return <BoardDiagram source={b.source as string} title={b.title} theme={theme} />;
    case "tiles": {
      const values = (b.rendered?.values ?? []) as (number | null)[];
      return (
        <ul className="board-tiles">
          {(s.tiles as Tile[]).map((t, i) => (
            <li key={i} className="board-tile">
              <span className="board-tile-label">{t.label}</span>
              <span className="board-tile-value">{tileValue(values[i] ?? null, t.format)}</span>
              {typeof t.change === "number" && <span className="board-tile-change">{tileChange(t.change, t.format)}</span>}
              {t.note && <span className="board-tile-note">{t.note}</span>}
            </li>
          ))}
        </ul>
      );
    }
    case "checklist": {
      const items = s.items as ChecklistItem[];
      return (
        <ul className="board-checklist">
          {items.map((it, i) => (
            <li key={i}>
              <label>
                <input type="checkbox" checked={it.done} onChange={() => onTick(items.map((x, k) => (k === i ? { ...x, done: !x.done } : x)))} />
                <span>{it.text}</span>
              </label>
            </li>
          ))}
        </ul>
      );
    }
  }
}

function BoardTable({ columns, rows }: { columns: string[]; rows: Cell[][] }) {
  return (
    <div className="board-table-box" tabIndex={0} role="region" aria-label="Table">
      <table className="board-table">
        <thead><tr>{columns.map((c, i) => <th key={i} scope="col">{c}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{r.map((v, k) => <td key={k} className={typeof v === "number" ? "num" : undefined}>{v === null ? "" : String(v)}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function inline(xs: Inline[]): ReactNode[] {
  return xs.map((x, i) => {
    if (x.t === "text") return x.text;
    if (x.t === "code") return <code key={i}>{x.text}</code>;
    if (x.t === "b") return <strong key={i}>{inline(x.children)}</strong>;
    if (x.t === "i") return <em key={i}>{inline(x.children)}</em>;
    return <a key={i} href={x.href} target="_blank" rel="noopener noreferrer">{inline(x.children)}</a>;
  });
}

/** A note's Markdown subset; everything else, raw HTML included, is text. */
function markdown(src: string): ReactNode {
  return parseMarkdown(src).map((b, i) => {
    if (b.t === "p") return <p key={i}>{inline(b.children)}</p>;
    if (b.t === "h") {
      const H = `h${Math.min(6, b.level + 3)}` as "h4";
      return <H key={i}>{inline(b.children)}</H>;
    }
    const L = b.t;
    return <L key={i}>{b.items.map((it, k) => <li key={k}>{inline(it)}</li>)}</L>;
  });
}

const FRAME_SRC = `${import.meta.env.BASE_URL}board-diagram.html`;

/** A diagram or flow, drawn by Mermaid inside its own sandboxed frame (Amendment 1d), then the group legend. */
function BoardDiagram({ source, title, theme }: { source: string; title: string; theme: DiagramTheme | null }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [loaded, setLoaded] = useState(false);
  const [height, setHeight] = useState<number | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    const onMessage = (e: MessageEvent<FromFrame>) => {
      if (!frame.current || e.source !== frame.current.contentWindow || e.origin !== location.origin) return;
      if (e.data?.type === "drawn" && typeof e.data.height === "number") { setFailed(null); setHeight(e.data.height); }
      else if (e.data?.type === "error") setFailed(firstLine(String(e.data.message)));
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);
  useEffect(() => {
    if (!loaded || !theme) return;
    const msg: ToFrame = { type: "draw", source, theme };
    frame.current?.contentWindow?.postMessage(msg, location.origin);
  }, [loaded, source, theme]);

  const groups = diagramGroups(source);
  const emphasis = hasEmphasis(source);
  return (
    <div className="board-diagram">
      <iframe ref={frame} src={FRAME_SRC} sandbox="allow-scripts allow-same-origin" title={`Diagram: ${title}`}
        className="board-frame" hidden={failed !== null} style={{ height: height ?? 64 }} onLoad={() => setLoaded(true)} />
      {failed !== null ? (
        <>
          <p className="board-note-line">This diagram could not be drawn: {failed}</p>
          <pre className="mono board-source">{source}</pre>
        </>
      ) : (
        (groups.length > 0 || emphasis) && (
          <p className="board-legend">
            {groups.map((g, i) => (
              <span key={g} className="board-legend-item">
                <i aria-hidden="true" style={{ background: theme?.groups[i].fill, borderColor: theme?.groups[i].stroke }} />
                {groupLabel(g)}
              </span>
            ))}
            {emphasis && <span className="board-legend-key">Bold outline: key step</span>}
          </p>
        )
      )}
    </div>
  );
}

/** The page's colours as the diagram frame needs them, resolved to hex, and again whenever the theme changes. */
function useDiagramTheme(): DiagramTheme | null {
  const [theme, setTheme] = useState<DiagramTheme | null>(null);
  useEffect(() => {
    const read = () => setTheme(readTheme());
    read();
    const media = matchMedia("(prefers-color-scheme: dark)");
    const observer = new MutationObserver(read);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    media.addEventListener("change", read);
    return () => { observer.disconnect(); media.removeEventListener("change", read); };
  }, []);
  return theme;
}

function readTheme(): DiagramTheme {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  const probe = document.createElement("span");
  probe.style.display = "none";
  document.body.append(probe);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
  const computed = (css: string) => {
    probe.style.color = "";
    probe.style.color = css;
    return getComputedStyle(probe).color;
  };
  const ground = computed("var(--panel)");
  const hex = (css: string) => {
    ctx.fillStyle = ground; // a colour with alpha (dark --panel-border) is seen over the panel
    ctx.fillRect(0, 0, 1, 1);
    ctx.fillStyle = computed(css);
    ctx.fillRect(0, 0, 1, 1);
    const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
    return `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`;
  };
  const theme: DiagramTheme = {
    dark,
    font: getComputedStyle(root).getPropertyValue("--font-display").trim(),
    panel: hex("var(--panel)"),
    text: hex("var(--text)"),
    muted: hex("var(--muted)"),
    line: hex("var(--field-border)"),
    hair: hex("var(--panel-border)"),
    well: hex("var(--well)"),
    groups: GROUP_SLOTS.map((v) => ({
      fill: hex(`color-mix(in oklch, var(${v}) 14%, var(--panel))`),
      stroke: hex(`var(${v})`),
      text: hex(`color-mix(in oklch, var(${v}) 65%, var(--text))`),
    })),
  };
  probe.remove();
  return theme;
}
