// Refine threads on the Agent screen (spec refine-chat-design, amendment 2026-11-22): the picker and the chat go in the
// stream, the document in the stage's `Document` tab. Agent.tsx mounts these; the rules live in lib/agent.ts.
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { announce } from "../lib/announce";
import {
  overflowing, refineChanged, refineErrorText, refineHistory, refineProgress, refineResultLines, refineRunning, refineTitle,
  type RefineKind,
} from "../lib/agent";
import { usePoll } from "../lib/poll";
import { STATUS_BADGE } from "../lib/rfp";
import { useChartWidth } from "../lib/useChartWidth";
import type { RefineDocument, RefineThread, RefineTurn, RefineTurnOut, ReportManifest, RfpProject } from "../types";
import { StepTabs } from "./StepTabs";

const RUNNING_MS = 1000; // while a turn runs: the turn and the document
const IDLE_MS = 3000; // otherwise: the document and the turn list, so other people's edits show

export type RefineDocRef = { kind: RefineKind; docId: string };

/** Every document with a turn, re-read every 3 s, for the threads column. */
export function useRefineThreads(onError: (message: string) => void): RefineThread[] {
  const [threads, setThreads] = useState<RefineThread[]>([]);
  usePoll(() => api.listRefineThreads().then(setThreads, (e: Error) => onError(`Refine threads could not be loaded: ${e.message}.`)), IDLE_MS);
  return threads;
}

/** A turn as `GET /api/refine/turns/<id>` reads it, laid over the same turn from the list. */
const withTurn = (t: RefineTurn, out: RefineTurnOut): RefineTurn =>
  t.turn_id !== out.id ? t : { ...t, status: out.status, done: out.done, total: out.total, changed: out.changed, not_changed: out.not_changed,
    check_figures: out.check_figures, error: out.error, reply: out.status === "running" ? t.reply : out.reply };

export type Refine = ReturnType<typeof useRefine>;

/** One Refine thread's state, shared by its stream, composer and stage: the stored turns, the document, and the
 * writes. `doc` null (the picker, or another thread kind) keeps it idle. */
export function useRefine(doc: RefineDocRef | null) {
  const key = doc ? `${doc.kind}/${doc.docId}` : null;
  const [turns, setTurns] = useState<RefineTurn[] | null>(null);
  const [project, setProject] = useState<RfpProject | null>(null);
  const [html, setHtml] = useState<string | null>(null);
  const [manifest, setManifest] = useState<ReportManifest | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null); // under the composer
  const [undoError, setUndoError] = useState<string | null>(null); // under Undo
  const [posting, setPosting] = useState(false);
  const [undoing, setUndoing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const shown = useRef(key); // the thread on screen, so an answer for another one is dropped
  shown.current = key;

  const running = turns ? refineRunning(turns) : null;

  /** Fetches the document; the returned function shows it, so a turn and its edits show in one render. */
  const fetchDoc = useCallback(async (): Promise<() => void> => {
    if (!doc) return () => {};
    if (doc.kind === "rfp") {
      const p = await api.getRfpProject(Number(doc.docId));
      return () => setProject(p);
    }
    const [h, m] = await Promise.all([api.getDeckHtml(doc.docId), api.getReport(doc.docId)]);
    return () => {
      setHtml(h);
      setManifest(m);
    };
  }, [doc?.kind, doc?.docId]); // eslint-disable-line react-hooks/exhaustive-deps -- the doc's value, not its object

  const reload = useCallback(async () => {
    if (!doc) return;
    const asked = key;
    try {
      const [list, show] = await Promise.all([api.listRefineTurns(doc.kind, doc.docId), fetchDoc()]);
      if (shown.current !== asked) return;
      setTurns(list);
      show();
      setLoadError(null);
    } catch (e) {
      if (shown.current === asked) setLoadError((e as Error).message);
    }
  }, [doc?.kind, doc?.docId, fetchDoc]); // eslint-disable-line react-hooks/exhaustive-deps

  // A new thread starts empty and loads at once.
  useEffect(() => {
    setTurns(null);
    setProject(null);
    setHtml(null);
    setManifest(null);
    setError(null);
    setUndoError(null);
    setLoadError(null);
    void reload();
  }, [reload]);

  usePoll(async () => {
    if (!running) return reload();
    const asked = key;
    try {
      // The turn is read before the document, so a finished reply never shows before its edits; both show together.
      const out = await api.getRefineTurn(running.turn_id);
      const show = await fetchDoc();
      if (shown.current !== asked) return;
      setTurns((ts) => ts && ts.map((t) => withTurn(t, out)));
      show();
      if (out.status !== "running") {
        announce(out.status === "failed" ? "The change failed." : "The change finished.");
        void reload(); // the list has the finished turn as stored
      }
    } catch (e) {
      if (shown.current === asked) setLoadError((e as Error).message);
    }
  }, running ? RUNNING_MS : IDLE_MS, doc !== null && turns !== null);

  /** Posts an instruction; true once the API took it (202). */
  async function send(message: string): Promise<boolean> {
    if (!doc || !turns) return false;
    setPosting(true);
    setError(null);
    const r = await api.refineWrite(`/api/refine/${doc.kind}/${encodeURIComponent(doc.docId)}/turns`, { message, history: refineHistory(turns) });
    if (r.status === 202) await reload(); // shows the new turn as `Working…`
    else setError(refineErrorText(r.status, r.body));
    setPosting(false);
    return r.status === 202;
  }

  async function undo() {
    if (!doc) return;
    setUndoing(true);
    setUndoError(null);
    const r = await api.refineWrite(`/api/refine/${doc.kind}/${encodeURIComponent(doc.docId)}/undo`);
    if (r.status === 200) {
      announce("Last turn undone.");
      await reload();
    } else {
      setUndoError(refineErrorText(r.status, r.body));
    }
    setUndoing(false);
  }

  async function exportDeck() {
    if (!doc || doc.kind !== "deck") return;
    setExporting(true);
    setUndoError(null);
    try {
      const m = await api.renderReport(doc.docId);
      if (shown.current === `deck/${doc.docId}`) setManifest(m);
    } catch (e) {
      setUndoError((e as Error).message);
    } finally {
      setExporting(false);
    }
  }

  const title = doc?.kind === "rfp" && project ? refineTitle("rfp", project.investor)
    : doc?.kind === "deck" && manifest ? refineTitle("deck", manifest.title || manifest.report_id) : null;
  return {
    doc, turns, running, title, project, html, manifest, loadError, error, undoError, exporting,
    /** The composer is closed while anyone's turn runs on the document, and while this one is being sent. */
    busy: posting || running !== null,
    undoing, send, undo, exportDeck,
  };
}

/** The picker (`#/agent/refine`): every document that can be refined, RFP responses first. */
export function RefinePicker() {
  const [docs, setDocs] = useState<RefineDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.listRefineDocuments().then(setDocs, (e: Error) => setError(`The documents could not be loaded: ${e.message}.`));
  }, []);
  const groups: { kind: RefineKind; heading: string; empty: string }[] = [
    { kind: "rfp", heading: "RFP responses", empty: "No RFP projects yet. Import one on RFP Answers." },
    { kind: "deck", heading: "Decks", empty: "No decks yet. Approve a storyline in Report Builder to build one." },
  ];
  return (
    <section className="refine-picker" aria-labelledby="refine-picker-h">
      <h2 id="refine-picker-h">Refine a document</h2>
      <p className="muted">Pick an RFP response or a deck, then say what to change. The document shows in the stage as it changes.</p>
      {error && <p className="error-text" role="alert">{error}</p>}
      {docs === null && !error && <p className="muted">Loading…</p>}
      {docs && groups.map((g) => {
        const items = docs.filter((d) => d.kind === g.kind);
        return (
          <div key={g.kind} className="refine-picker-group">
            <h3 id={`refine-picker-${g.kind}`}>{g.heading}</h3>
            {items.length === 0 ? <p className="muted">{g.empty}</p> : (
              <ul aria-labelledby={`refine-picker-${g.kind}`}>
                {items.map((d) => (
                  <li key={d.doc_id}>
                    <a className="agent-link-card" href={`#/agent/refine/${d.kind}/${encodeURIComponent(d.doc_id)}`}>{d.title}</a>
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </section>
  );
}

/** A Refine thread's stream: one entry per stored turn, oldest first. */
export function RefineStream({ refine, emptyLine }: { refine: Refine; emptyLine: string }) {
  const { doc, turns, title, loadError } = refine;
  if (!doc) return null;
  return (
    <>
      <h2 className="refine-title">{title ?? "Refine"}</h2>
      {loadError && <p className="error-text" role="alert">{loadError}</p>}
      {turns === null ? <p className="muted">Loading…</p> : turns.length === 0 ? (
        <p className="muted">{emptyLine}</p>
      ) : (
        <ol className="agent-calls" aria-label="Turns">
          {turns.map((t) => (
            <li key={t.turn_id} className="ask-turn">
              <p className="ask-question"><span className="refine-who">{t.user_id}</span> {t.message}</p>
              <div className="ask-card refine-reply">
                {t.status === "running" ? <p className="muted" role="status">Working…</p>
                  : t.status === "failed" ? <p className="error-text">{t.error ?? "The change failed."}</p>
                  : <p>{t.reply}</p>}
                {t.status === "undone" && <p><span className="chip refine-undone">undone</span></p>}
                {t.status !== "running" && refineResultLines(doc.kind, t).map((line) => <p key={line} className="muted refine-line">{line}</p>)}
              </div>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}

/** The stage of a Refine thread: `Undo last turn`, then one tab, `Document`, holding the live view. */
export function RefineStage({ refine, canUndo, idPrefix, head }: { refine: Refine; canUndo: boolean; idPrefix: string; head?: ReactNode }) {
  const { doc, turns, running, project, html, manifest, undoError, undoing, exporting } = refine;
  const changed = turns ? refineChanged(turns) : [];
  return (
    <>
      <div className="agent-side-head">
        <StepTabs label="Stage" tabs={[{ id: "document", label: "Document" }]} active="document" onSelect={() => {}} />
        {head}
      </div>
      {doc && canUndo && (
        <div className="refine-undo">
          <button type="button" className="secondary" disabled={undoing || running !== null || turns === null} onClick={() => void refine.undo()}>
            Undo last turn
          </button>
          {undoError && <p className="error-text" role="alert">{undoError}</p>}
        </div>
      )}
      <div id={`${idPrefix}-panel`} role="tabpanel" aria-label="Document">
        {!doc ? (
          <p className="muted">Pick a document; it shows here as it changes.</p>
        ) : (
          <>
            {/* Always rendered, so the first progress line is announced. */}
            <p className="refine-progress" role="status">{running && doc.kind === "rfp" ? refineProgress(running) : ""}</p>
            {doc.kind === "rfp" ? <RfpView project={project} changed={changed} /> : (
              <>
                {manifest?.deck_edited_since_render && (
                  <div className="refine-export">
                    <p className="muted">Preview changed since last export</p>
                    <button type="button" disabled={exporting || running !== null} onClick={() => void refine.exportDeck()}>
                      {exporting ? "Exporting…" : "Export .pptx"}
                    </button>
                  </div>
                )}
                <DeckView html={html} changed={changed} />
              </>
            )}
          </>
        )}
      </div>
    </>
  );
}

function RfpView({ project, changed }: { project: RfpProject | null; changed: number[] }) {
  if (!project) return <p className="muted">Loading…</p>;
  if (project.questions.length === 0) return <p className="muted">No questions found yet.</p>;
  return (
    <ol className="refine-items" aria-label="Questions">
      {project.questions.map((q) => (
        <li key={q.id} className="refine-item" aria-label={`Q${q.id}`}>
          <h3>Q{q.id} {q.question}</h3>
          <div className="chip-row">
            <span className={STATUS_BADGE[q.status] ?? "badge"}>{q.status}</span>
            {q.flags.map((f) => <span key={f} className="chip chip-warn">{f}</span>)}
            {changed.includes(q.id) && <span className="chip chip-changed">changed</span>}
          </div>
          <p className="refine-answer">{q.answer || <span className="muted">No answer yet.</span>}</p>
          {q.sources.length > 0 && (
            <ul className="refine-sources">
              {q.sources.map((s, i) => (
                <li key={i}><strong>{s.entry_question}</strong> “{s.quote}”</li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ol>
  );
}

function DeckView({ html, changed }: { html: string | null; changed: number[] }) {
  const [selected, setSelected] = useState(1);
  const [over, setOver] = useState<string[]>([]);
  const count = useMemo(() => (html ? new DOMParser().parseFromString(html, "text/html").querySelectorAll("section[data-slide]").length : 0), [html]);
  const [wrapRef, width] = useChartWidth(600, 200);
  if (html === null) return <p className="muted">Loading…</p>;
  const slide = Math.min(selected, count);
  return (
    <>
      <ul className="refine-thumbs" aria-label="Slides">
        {Array.from({ length: count }, (_, i) => i + 1).map((n) => (
          <li key={n} className={n === slide ? "refine-thumb active" : "refine-thumb"}>
            <SlideFrame html={html} slide={n} width={96} title={`Slide ${n} thumbnail`} hidden />
            <span className="refine-thumb-label" aria-hidden="true">
              {n}{changed.includes(n) && <span className="chip chip-changed">changed</span>}
            </span>
            {/* Laid over the thumbnail, so the iframe stays outside the button. */}
            <button type="button" className="refine-thumb-hit" aria-label={changed.includes(n) ? `Slide ${n}, changed` : `Slide ${n}`}
              aria-current={n === slide ? "true" : undefined} onClick={() => { setOver([]); setSelected(n); }} />
          </li>
        ))}
      </ul>
      <div ref={wrapRef} className="refine-slide">
        {count > 0 && <SlideFrame key={slide} html={html} slide={slide} width={width} title={`Slide ${slide}`} onOverflow={setOver} />}
      </div>
      {count > 0 && over.length > 0 && <p className="refine-overflow">Text doesn't fit: {over.join(", ")}</p>}
    </>
  );
}

// shortcut: the house canvas is 1920x1080 (reporting/style/tokens.json); read it from the HTML if decks get other sizes.
const CANVAS = { w: 1920, h: 1080 };
const MARK_CSS =
  ".arp-overflow{outline:8px solid #c8323f!important;outline-offset:-8px}" +
  ".arp-overflow-label{position:absolute;top:0;right:0;z-index:9;background:#c8323f;color:#fff;font:600 40px/1.3 system-ui,sans-serif;padding:6px 16px}";

/** One slide of the deck HTML, scaled to `width`, in a sandboxed iframe (no scripts; same origin so the screen can mark
 * slots whose text does not fit: a red outline and the label `Text doesn't fit`). */
function SlideFrame({ html, slide, width, title, hidden = false, onOverflow }: {
  html: string; slide: number; width: number; title: string; hidden?: boolean; onOverflow?: (slots: string[]) => void;
}) {
  const ref = useRef<HTMLIFrameElement>(null);
  // data-slide is the 0-based index; `slide` is the 1-based position.
  const srcDoc = html.replace("</head>", `<style>section.slide:not([data-slide="${slide - 1}"]){display:none}${MARK_CSS}</style></head>`);
  const scale = width / CANVAS.w;
  function mark() {
    const doc = ref.current?.contentDocument;
    if (!doc) return;
    void doc.fonts.ready.then(() => {
      const over = [...doc.querySelectorAll<HTMLElement>(`[data-slide="${slide - 1}"][data-slot]`)].filter(overflowing);
      for (const el of over) {
        el.classList.add("arp-overflow");
        const label = doc.createElement("span");
        label.className = "arp-overflow-label";
        label.textContent = "Text doesn't fit";
        el.append(label);
      }
      onOverflow?.(over.map((el) => el.dataset.slot ?? ""));
    });
  }
  return (
    <div className="refine-frame" style={{ width, height: CANVAS.h * scale }}>
      <iframe ref={ref} title={title} sandbox="allow-same-origin" srcDoc={srcDoc} onLoad={mark} tabIndex={-1} aria-hidden={hidden || undefined}
        style={{ width: CANVAS.w, height: CANVAS.h, transform: `scale(${scale})` }} />
    </div>
  );
}
